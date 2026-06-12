"""
统一的资源管理层，用于 Folium HTML 资源渲染管线。

核心职责划分：
- ResourceEntry: 声明式资源描述（元数据，无逻辑）
- ResourceStrategy: 资源加载策略枚举
- ResourceRegistry: 集中管理所有已知资源的元数据
- ResolvedResource: 渲染阶段消费的最终资源条目（纯数据）
- ResourceResolver: 下载、缓存、校验、fallback 逻辑（纯逻辑层）
- ResourceContext: 持有策略配置，收集资源声明，协调解析

渲染流程：
    组件声明 ResourceEntry
        → 收集到 ResourceContext
        → ResourceResolver 解析（下载/缓存/校验/fallback）
        → ResolvedResource 列表
        → 渲染层只消费 ResolvedResource（注入 HTML）
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from urllib.parse import urlparse, urljoin
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class ResourceType(Enum):
    """资源类型枚举。"""
    JAVASCRIPT = "javascript"
    CSS = "css"


class ResourceStrategy(Enum):
    """资源加载策略枚举。

    策略优先级（从高到低）：
        1. INLINE: 内联到 HTML 中（离线、无网络依赖）
        2. LOCAL: 使用本地文件路径（相对或绝对）
        3. MIRROR: 使用企业内网镜像
        4. CDN: 使用远程 CDN URL（默认）
    """
    CDN = "cdn"
    LOCAL = "local"
    INLINE = "inline"
    MIRROR = "mirror"


@dataclass
class ResourceEntry:
    """声明式资源描述。

    仅包含资源元数据，不包含实际内容或逻辑。
    所有组件（Map、插件等）通过此类声明其依赖的资源。

    Parameters
    ----------
    name:
        资源唯一标识名，用于去重和引用
    url:
        资源的主要 CDN URL
    resource_type:
        资源类型（javascript/css）
    sha256:
        SHA256 哈希值（十六进制），用于 Python 端下载校验
    fallback_urls:
        备用 URL 列表，当主 URL 失败时尝试
    local_path:
        本地文件路径（相对于 folium 包或绝对路径）
    integrity:
        SRI 完整性属性（sha256-xxx 格式），用于浏览器端校验
    crossorigin:
        跨域属性，默认为 "anonymous"

    Notes
    -----
    sha256 和 integrity 字段用途不同但相关：
    - sha256: 纯十六进制哈希，用于 Python 端下载时校验
    - integrity: SRI 格式，用于浏览器端子资源完整性校验
    如果只设置其中一个，另一个会自动推导。
    """

    name: str
    url: str
    resource_type: ResourceType
    sha256: Optional[str] = None
    fallback_urls: list[str] = field(default_factory=list)
    local_path: Optional[str] = None
    integrity: Optional[str] = None
    crossorigin: str = "anonymous"

    def __post_init__(self) -> None:
        """一致性校验：确保 sha256 和 integrity 字段一致。

        如果只设置了一个字段，自动推导另一个字段。
        如果两个都设置了，确保它们表示同一个哈希值。
        """
        import base64

        if self.sha256 is not None and self.integrity is None:
            # 从 sha256 推导 integrity
            hash_bytes = bytes.fromhex(self.sha256)
            self.integrity = f"sha256-{base64.b64encode(hash_bytes).decode('ascii')}"
        elif self.integrity is not None and self.sha256 is None:
            # 从 integrity 推导 sha256
            if self.integrity.startswith("sha256-"):
                b64_hash = self.integrity[7:]
                hash_bytes = base64.b64decode(b64_hash)
                self.sha256 = hash_bytes.hex()
        elif self.sha256 is not None and self.integrity is not None:
            # 两个都设置了，确保一致
            import base64
            hash_bytes = bytes.fromhex(self.sha256)
            expected_integrity = f"sha256-{base64.b64encode(hash_bytes).decode('ascii')}"
            if self.integrity != expected_integrity:
                raise ValueError(
                    f"ResourceEntry '{self.name}': sha256 and integrity mismatch. "
                    f"sha256={self.sha256}, integrity={self.integrity}, "
                    f"expected integrity={expected_integrity}"
                )

    @staticmethod
    def _hex_to_sri(hex_hash: str) -> str:
        """将十六进制 SHA256 哈希转换为 SRI 格式。"""
        import base64
        hash_bytes = bytes.fromhex(hex_hash)
        return f"sha256-{base64.b64encode(hash_bytes).decode('ascii')}"

    @staticmethod
    def _sri_to_hex(sri: str) -> str:
        """将 SRI 格式的哈希转换为十六进制。"""
        import base64
        if not sri.startswith("sha256-"):
            raise ValueError(f"Unsupported SRI algorithm: {sri}")
        b64_hash = sri[7:]
        hash_bytes = base64.b64decode(b64_hash)
        return hash_bytes.hex()

    @classmethod
    def from_tuple(
        cls,
        entry: tuple[str, str],
        resource_type: ResourceType,
    ) -> "ResourceEntry":
        """从旧版 (name, url) 元组格式创建 ResourceEntry。

        用于向后兼容 default_js/default_css 接口。
        """
        name, url = entry
        return cls(
            name=name,
            url=url,
            resource_type=resource_type,
        )

    def to_tuple(self) -> tuple[str, str]:
        """转换为旧版 (name, url) 元组格式，用于向后兼容。"""
        return (self.name, self.url)


@dataclass
class ResolvedResource:
    """渲染阶段消费的最终资源条目。

    包含已解析的最终 URL 或内联内容，以及渲染所需的所有属性。
    渲染层只消费此类，不涉及任何策略决策或网络操作。
    """

    name: str
    resource_type: ResourceType
    url: Optional[str] = None
    content: Optional[str] = None
    inline: bool = False
    integrity: Optional[str] = None
    crossorigin: Optional[str] = None
    source: str = "unknown"  # cdn/local/inline/mirror/cache/fallback

    def __post_init__(self) -> None:
        """一致性校验：确保 inline 标记和 content 字段状态一致。"""
        if self.inline and self.content is None:
            raise ValueError(
                f"ResolvedResource '{self.name}': inline=True but content is None"
            )
        if self.content is not None and not self.inline:
            self.inline = True

    @property
    def is_inline(self) -> bool:
        """是否为内联资源。"""
        return self.inline


class ResourceRegistry:
    """集中管理所有已知资源的元数据。

    替代原先分散在各个模块的 default_js/default_css 定义。
    提供资源注册、查询、版本管理功能。
    """

    def __init__(self) -> None:
        self._resources: dict[str, ResourceEntry] = {}

    def register(self, entry: ResourceEntry) -> None:
        """注册一个资源。"""
        self._resources[entry.name] = entry

    def register_many(self, entries: Iterable[ResourceEntry]) -> None:
        """批量注册资源。"""
        for entry in entries:
            self.register(entry)

    def get(self, name: str) -> Optional[ResourceEntry]:
        """按名称查询资源。"""
        return self._resources.get(name)

    def get_all(self) -> list[ResourceEntry]:
        """获取所有已注册资源。"""
        return list(self._resources.values())

    def register_from_tuples(
        self,
        entries: Iterable[tuple[str, str]],
        resource_type: ResourceType,
    ) -> list[ResourceEntry]:
        """从 (name, url) 元组列表注册资源，返回创建的 ResourceEntry 列表。"""
        result = []
        for entry in entries:
            resource_entry = ResourceEntry.from_tuple(entry, resource_type)
            self.register(resource_entry)
            result.append(resource_entry)
        return result

    def unregister(self, name: str) -> None:
        """移除已注册的资源。"""
        self._resources.pop(name, None)

    def clear(self) -> None:
        """清空所有资源。"""
        self._resources.clear()


@dataclass
class ResourceResolverConfig:
    """ResourceResolver 的配置。"""

    cache_dir: Optional[Path] = None
    mirror_base_url: Optional[str] = None
    offline_mode: bool = False
    audit_mode: bool = False
    allow_fallback_to_cdn: bool = True
    timeout: int = 30
    user_agent: str = "folium/resource-resolver"

    def __post_init__(self) -> None:
        if self.cache_dir is None:
            self.cache_dir = Path(tempfile.gettempdir()) / "folium_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)


class ResourceResolver:
    """资源解析器，负责下载、缓存、校验、fallback 逻辑。

    纯逻辑层，与网络和文件系统交互。
    不持有策略配置，不做渲染相关决策。

    支持审计模式：记录所有资源访问，用于安全审计。
    """

    def __init__(
        self,
        config: Optional[ResourceResolverConfig] = None,
    ) -> None:
        self.config = config or ResourceResolverConfig()
        self._audit_log: list[dict[str, Any]] = []

    def resolve(
        self,
        entry: ResourceEntry,
        strategy: ResourceStrategy = ResourceStrategy.CDN,
    ) -> ResolvedResource:
        """解析单个 ResourceEntry 为 ResolvedResource。

        支持自动降级：当非 CDN 策略解析失败且 allow_fallback_to_cdn=True 时，
        自动降级到 CDN 策略作为安全网。
        """
        self._audit(f"resolve_start", entry.name, {"strategy": strategy.value})

        try:
            if strategy == ResourceStrategy.INLINE:
                return self._resolve_inline(entry)
            if strategy == ResourceStrategy.LOCAL:
                return self._resolve_local(entry)
            if strategy == ResourceStrategy.MIRROR:
                return self._resolve_mirror(entry)
            return self._resolve_cdn(entry)
        except Exception as e:
            self._audit("resolve_failed", entry.name, {"error": str(e)})

            # 首先尝试 fallback URLs
            if entry.fallback_urls:
                try:
                    return self._resolve_fallback(entry)
                except Exception as fallback_e:
                    self._audit(
                        "fallback_failed",
                        entry.name,
                        {"error": str(fallback_e)},
                    )

            # 如果非 CDN 策略失败且允许降级到 CDN，尝试 CDN 策略
            if (
                strategy != ResourceStrategy.CDN
                and self.config.allow_fallback_to_cdn
                and not self.config.offline_mode
            ):
                self._audit(
                    "fallback_to_cdn",
                    entry.name,
                    {"original_strategy": strategy.value},
                )
                try:
                    return self._resolve_cdn(entry)
                except Exception as cdn_e:
                    self._audit(
                        "cdn_fallback_failed",
                        entry.name,
                        {"error": str(cdn_e)},
                    )
                    raise RuntimeError(
                        f"Resource '{entry.name}' failed: {e}. "
                        f"Fallback to CDN also failed: {cdn_e}"
                    ) from cdn_e

            raise

    def resolve_all(
        self,
        entries: Iterable[ResourceEntry],
        strategy: ResourceStrategy = ResourceStrategy.CDN,
    ) -> list[ResolvedResource]:
        """批量解析资源，自动去重。"""
        seen: set[str] = set()
        result: list[ResolvedResource] = []
        for entry in entries:
            if entry.name in seen:
                continue
            seen.add(entry.name)
            result.append(self.resolve(entry, strategy))
        return result

    def _resolve_cdn(self, entry: ResourceEntry) -> ResolvedResource:
        """从 CDN 解析资源。

        CDN 策略只需要返回 URL，不需要下载内容。
        仅当配置了 SHA256 校验时才下载内容进行验证。

        如果没有 integrity，crossorigin 也设为 None（向后兼容），
        因为 SRI 规范中 crossorigin 仅在 integrity 存在时才有意义。
        """
        if self.config.offline_mode:
            return self._resolve_cached(entry)

        if entry.sha256 is not None:
            self._download_with_cache(entry.url, entry.sha256)

        crossorigin = entry.crossorigin if entry.integrity else None

        return ResolvedResource(
            name=entry.name,
            resource_type=entry.resource_type,
            url=entry.url,
            integrity=entry.integrity,
            crossorigin=crossorigin,
            source="cdn",
        )

    @staticmethod
    def _resolve_local_path(local_path: str) -> Path:
        """解析本地资源路径。

        相对路径相对于 folium 包目录解析。
        使用 Path(__file__).parent 避免循环导入。
        """
        path = Path(local_path)
        if not path.is_absolute():
            path = Path(__file__).parent / path
        return path

    def _resolve_local(self, entry: ResourceEntry) -> ResolvedResource:
        """从本地文件解析资源。"""
        if entry.local_path is None:
            raise ValueError(
                f"Resource '{entry.name}' has no local_path configured "
                f"for LOCAL strategy."
            )

        local_path = self._resolve_local_path(entry.local_path)

        if not local_path.exists():
            raise FileNotFoundError(
                f"Local resource not found: {local_path}"
            )

        return ResolvedResource(
            name=entry.name,
            resource_type=entry.resource_type,
            url=str(local_path),
            integrity=entry.integrity,
            crossorigin=None,
            source="local",
        )

    def _resolve_inline(self, entry: ResourceEntry) -> ResolvedResource:
        """内联资源内容到 HTML。"""
        content = self._get_resource_content(entry)
        return ResolvedResource(
            name=entry.name,
            resource_type=entry.resource_type,
            content=content,
            inline=True,
            integrity=None,
            crossorigin=None,
            source="inline",
        )

    def _resolve_mirror(self, entry: ResourceEntry) -> ResolvedResource:
        """从企业内网镜像解析资源。

        MIRROR 策略只需要重写 URL，不需要下载内容。
        仅当配置了 SHA256 校验时才下载内容进行验证。
        """
        if self.config.mirror_base_url is None:
            raise ValueError(
                "MIRROR strategy requires mirror_base_url to be configured."
            )

        parsed_url = urlparse(entry.url)
        mirror_url = urljoin(
            self.config.mirror_base_url,
            parsed_url.path.lstrip("/"),
        )

        # 仅当需要 SHA256 校验时才下载内容
        if entry.sha256 is not None:
            self._download_with_cache(mirror_url, entry.sha256)

        crossorigin = entry.crossorigin if entry.integrity else None

        return ResolvedResource(
            name=entry.name,
            resource_type=entry.resource_type,
            url=mirror_url,
            integrity=entry.integrity,
            crossorigin=crossorigin,
            source="mirror",
        )

    def _resolve_fallback(self, entry: ResourceEntry) -> ResolvedResource:
        """使用 fallback URL 解析资源。"""
        for fallback_url in entry.fallback_urls:
            try:
                content = self._download_with_cache(fallback_url, entry.sha256)
                return ResolvedResource(
                    name=entry.name,
                    resource_type=entry.resource_type,
                    url=fallback_url,
                    integrity=entry.integrity,
                    crossorigin=entry.crossorigin,
                    source="fallback",
                )
            except Exception:
                continue

        raise RuntimeError(
            f"All fallback URLs failed for resource '{entry.name}'."
        )

    def _resolve_cached(self, entry: ResourceEntry) -> ResolvedResource:
        """从缓存解析资源（离线模式）。"""
        cache_path = self._get_cache_path(entry.url)
        if not cache_path.exists():
            raise RuntimeError(
                f"Offline mode: cache not found for resource '{entry.name}'."
            )
        crossorigin = entry.crossorigin if entry.integrity else None
        return ResolvedResource(
            name=entry.name,
            resource_type=entry.resource_type,
            url=entry.url,
            integrity=entry.integrity,
            crossorigin=crossorigin,
            source="cache",
        )

    def _download_with_cache(
        self,
        url: str,
        expected_sha256: Optional[str] = None,
    ) -> bytes:
        """下载资源并缓存，支持 SHA256 校验。"""
        cache_path = self._get_cache_path(url)

        if cache_path.exists():
            content = cache_path.read_bytes()
            if expected_sha256:
                self._verify_sha256(content, expected_sha256, url)
            self._audit("cache_hit", url, {"path": str(cache_path)})
            return content

        content = self._download(url)
        if expected_sha256:
            self._verify_sha256(content, expected_sha256, url)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        self._audit("download", url, {"cached": True})

        return content

    def _download(self, url: str) -> bytes:
        """下载资源（不含缓存逻辑）。"""
        headers = {"User-Agent": self.config.user_agent}
        request = urlopen(url, timeout=self.config.timeout)
        try:
            return request.read()
        finally:
            request.close()

    def _get_resource_content(self, entry: ResourceEntry) -> str:
        """获取资源内容（用于内联）。"""
        if entry.local_path:
            local_path = self._resolve_local_path(entry.local_path)
            if local_path.exists():
                return local_path.read_text(encoding="utf-8")

        content_bytes = self._download_with_cache(entry.url, entry.sha256)
        return content_bytes.decode("utf-8")

    def _get_cache_path(self, url: str) -> Path:
        """获取资源的缓存文件路径。"""
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        filename = f"{url_hash}_{os.path.basename(urlparse(url).path)}"
        return self.config.cache_dir / filename

    @staticmethod
    def _verify_sha256(
        content: bytes,
        expected_sha256: str,
        source: str,
    ) -> None:
        """验证内容的 SHA256 哈希。"""
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"SHA256 mismatch for {source}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )

    def _audit(
        self,
        action: str,
        target: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """记录审计日志。"""
        if not self.config.audit_mode:
            return
        self._audit_log.append(
            {
                "action": action,
                "target": target,
                "details": details or {},
            }
        )

    def get_audit_log(self) -> list[dict[str, Any]]:
        """获取审计日志（审计模式下）。"""
        return list(self._audit_log)

    def clear_audit_log(self) -> None:
        """清空审计日志。"""
        self._audit_log.clear()

    def export_manifest(
        self,
        entries: Iterable[ResourceEntry],
        output_path: Union[str, Path],
    ) -> None:
        """导出离线 manifest，供 CLI 工具使用。"""
        manifest = {
            "version": "1.0",
            "resources": [
                {
                    "name": entry.name,
                    "url": entry.url,
                    "type": entry.resource_type.value,
                    "sha256": entry.sha256,
                    "fallback_urls": entry.fallback_urls,
                }
                for entry in entries
            ],
        }
        Path(output_path).write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )


class ResourceContext:
    """资源上下文，持有策略配置并协调整个资源生命周期。

    每个 Figure 持有一个 ResourceContext 实例。
    收集所有子组件声明的 ResourceEntry，在渲染前统一解析。

    职责：
    - 持有全局资源策略配置
    - 收集所有组件声明的 ResourceEntry
    - 协调 ResourceResolver 进行批量解析
    - 向后兼容旧的 default_js/default_css 接口
    """

    def __init__(
        self,
        strategy: ResourceStrategy = ResourceStrategy.CDN,
        resolver: Optional[ResourceResolver] = None,
        resolver_config: Optional[ResourceResolverConfig] = None,
    ) -> None:
        self.strategy = strategy
        self.resolver = resolver or ResourceResolver(resolver_config)
        self._entries: list[ResourceEntry] = []
        self._resolved: Optional[list[ResolvedResource]] = None

    def add_resource(self, entry: ResourceEntry) -> None:
        """添加一个资源声明。"""
        self._entries.append(entry)
        self._resolved = None  # 失效缓存

    def add_resources(self, entries: Iterable[ResourceEntry]) -> None:
        """批量添加资源声明。"""
        self._entries.extend(entries)
        self._resolved = None  # 失效缓存

    def add_resources_from_tuples(
        self,
        entries: Iterable[tuple[str, str]],
        resource_type: ResourceType,
    ) -> None:
        """从 (name, url) 元组添加资源（向后兼容）。"""
        for entry in entries:
            self.add_resource(
                ResourceEntry.from_tuple(entry, resource_type)
            )

    def clear_resources(self) -> None:
        """清空所有资源声明。"""
        self._entries.clear()
        self._resolved = None

    def resolve_all(self) -> list[ResolvedResource]:
        """解析所有资源（缓存结果）。"""
        if self._resolved is None:
            self._resolved = self.resolver.resolve_all(
                self._entries,
                strategy=self.strategy,
            )
        return self._resolved

    def get_javascript_resources(self) -> list[ResolvedResource]:
        """获取所有已解析的 JavaScript 资源。"""
        return [
            r for r in self.resolve_all()
            if r.resource_type == ResourceType.JAVASCRIPT
        ]

    def get_css_resources(self) -> list[ResolvedResource]:
        """获取所有已解析的 CSS 资源。"""
        return [
            r for r in self.resolve_all()
            if r.resource_type == ResourceType.CSS
        ]

    def get_entries(self) -> list[ResourceEntry]:
        """获取所有资源声明（用于导出 manifest）。"""
        return list(self._entries)

    def export_manifest(self, output_path: Union[str, Path]) -> None:
        """导出离线 manifest。"""
        self.resolver.export_manifest(self._entries, output_path)

    def set_strategy(self, strategy: ResourceStrategy) -> None:
        """设置资源策略，会失效已解析缓存。"""
        if self.strategy != strategy:
            self.strategy = strategy
            self._resolved = None

    @property
    def audit_mode(self) -> bool:
        """是否启用审计模式。"""
        return self.resolver.config.audit_mode

    @audit_mode.setter
    def audit_mode(self, value: bool) -> None:
        self.resolver.config.audit_mode = value

    def get_audit_log(self) -> list[dict[str, Any]]:
        """获取审计日志。"""
        return self.resolver.get_audit_log()


_global_registry = ResourceRegistry()


def get_global_registry() -> ResourceRegistry:
    """获取全局资源注册表实例。"""
    return _global_registry
