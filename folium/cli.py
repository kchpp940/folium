"""
Folium 命令行工具，用于资源管理和离线部署。

提供以下功能：
- export-manifest: 导出资源 manifest
- download: 预下载所有资源到本地缓存
- verify: 验证资源完整性（SHA256 校验）
- audit: 审计资源使用情况
- offline-html: 生成包含内联资源的离线 HTML

边界清晰：
- CLI 层只处理命令行参数和用户交互
- 实际工作委托给 ResourceResolver 和 ResourceContext
- 渲染逻辑完全在渲染层，CLI 不涉及
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from folium.resources import (
    ResourceEntry,
    ResourceRegistry,
    ResourceResolver,
    ResourceResolverConfig,
    ResourceStrategy,
    ResourceType,
    get_global_registry,
)


def _load_manifest(manifest_path: Path) -> list[ResourceEntry]:
    """从 manifest 文件加载资源列表。"""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    entries = []
    for res in manifest.get("resources", []):
        entries.append(
            ResourceEntry(
                name=res["name"],
                url=res["url"],
                resource_type=ResourceType(res["type"]),
                sha256=res.get("sha256"),
                fallback_urls=res.get("fallback_urls", []),
            )
        )
    return entries


def _collect_map_resources(map_module: str) -> list[ResourceEntry]:
    """通过导入模块收集 Map 声明的资源。

    这允许 CLI 处理用户创建的 Map 对象中的资源。
    """
    import importlib

    module_path, attr_name = map_module.rsplit(":", 1)
    module = importlib.import_module(module_path)
    map_obj = getattr(module, attr_name)

    from folium.folium import Map

    if not isinstance(map_obj, Map):
        raise ValueError(f"{attr_name} is not a folium.Map instance")

    # 触发渲染以收集所有资源
    root = map_obj.get_root()
    ctx = getattr(root, "_resource_context", None)
    if ctx is None:
        raise ValueError("Map has no resource context")

    return ctx.get_entries()


def cmd_export_manifest(args: argparse.Namespace) -> int:
    """导出资源 manifest 命令。"""
    entries: list[ResourceEntry] = []

    if args.manifest:
        entries = _load_manifest(Path(args.manifest))
    elif args.map:
        entries = _collect_map_resources(args.map)
    else:
        # 使用全局注册表
        registry = get_global_registry()
        if not registry.get_all():
            print(
                "Warning: Global registry is empty. "
                "Use --manifest or --map to specify resources.",
                file=sys.stderr,
            )
        entries = registry.get_all()

    if args.add:
        for name, url in args.add:
            resource_type = (
                ResourceType.JAVASCRIPT
                if url.endswith(".js")
                else ResourceType.CSS
            )
            entries.append(
                ResourceEntry(
                    name=name,
                    url=url,
                    resource_type=resource_type,
                )
            )

    manifest = {
        "version": "1.0",
        "resources": [
            {
                "name": e.name,
                "url": e.url,
                "type": e.resource_type.value,
                "sha256": e.sha256,
                "fallback_urls": e.fallback_urls,
            }
            for e in entries
        ],
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"Exported {len(entries)} resources to {output}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    """预下载资源命令。"""
    entries = _load_manifest(Path(args.manifest))

    config = ResourceResolverConfig(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        timeout=args.timeout,
    )
    resolver = ResourceResolver(config=config)

    success_count = 0
    fail_count = 0

    for entry in entries:
        try:
            resolved = resolver.resolve(entry, strategy=ResourceStrategy.CDN)
            print(f"  ✓ {entry.name}: {resolved.source}")
            success_count += 1
        except Exception as e:
            print(f"  ✗ {entry.name}: {e}", file=sys.stderr)
            fail_count += 1

    print(f"\nDownloaded {success_count}/{len(entries)} resources")
    if args.verify:
        return cmd_verify(args)
    return 0 if fail_count == 0 else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """验证资源完整性命令。"""
    entries = _load_manifest(Path(args.manifest))

    config = ResourceResolverConfig(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        offline_mode=True,
    )
    resolver = ResourceResolver(config=config)

    valid_count = 0
    invalid_count = 0
    missing_count = 0

    for entry in entries:
        try:
            if entry.sha256:
                cache_path = resolver._get_cache_path(entry.url)
                if not cache_path.exists():
                    print(f"  ? {entry.name}: not cached")
                    missing_count += 1
                    continue

                content = cache_path.read_bytes()
                try:
                    ResourceResolver._verify_sha256(
                        content, entry.sha256, entry.name
                    )
                    print(f"  ✓ {entry.name}: valid")
                    valid_count += 1
                except ValueError as e:
                    print(f"  ✗ {e}", file=sys.stderr)
                    invalid_count += 1
            else:
                print(f"  ~ {entry.name}: no SHA256 configured")
        except Exception as e:
            print(f"  ✗ {entry.name}: {e}", file=sys.stderr)
            invalid_count += 1

    print(
        f"\nValid: {valid_count}, Invalid: {invalid_count}, "
        f"Missing: {missing_count}"
    )
    return 0 if invalid_count == 0 else 1


def cmd_audit(args: argparse.Namespace) -> int:
    """审计资源使用命令。"""
    entries = _load_manifest(Path(args.manifest))

    config = ResourceResolverConfig(
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        audit_mode=True,
    )
    resolver = ResourceResolver(config=config)

    print("Auditing resources...\n")
    for entry in entries:
        try:
            resolver.resolve(entry, strategy=ResourceStrategy.CDN)
        except Exception as e:
            print(f"Warning: {entry.name}: {e}", file=sys.stderr)

    audit_log = resolver.get_audit_log()

    output = {
        "summary": {
            "total_resources": len(entries),
            "total_actions": len(audit_log),
        },
        "actions": audit_log,
    }

    if args.output:
        Path(args.output).write_text(
            json.dumps(output, indent=2), encoding="utf-8"
        )
        print(f"Audit log written to {args.output}")
    else:
        print(json.dumps(output, indent=2))

    return 0


def cmd_offline_html(args: argparse.Namespace) -> int:
    """生成离线 HTML 命令（内联所有资源）。"""
    import importlib

    module_path, attr_name = args.map.rsplit(":", 1)
    module = importlib.import_module(module_path)
    map_obj = getattr(module, attr_name)

    from folium.folium import Map

    if not isinstance(map_obj, Map):
        raise ValueError(f"{attr_name} is not a folium.Map instance")

    # 设置为 INLINE 策略
    map_obj.set_resource_strategy(ResourceStrategy.INLINE)

    html = map_obj.get_root().render()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    print(f"Offline HTML written to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="folium",
        description="Folium resource management CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # export-manifest
    export_parser = subparsers.add_parser(
        "export-manifest",
        help="Export resource manifest",
    )
    export_parser.add_argument(
        "--manifest",
        help="Input manifest file (to extend)",
    )
    export_parser.add_argument(
        "--map",
        help="Map object to collect resources from (module:attr)",
    )
    export_parser.add_argument(
        "--add",
        nargs=2,
        action="append",
        metavar=("NAME", "URL"),
        help="Add a resource (name url)",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        default="manifest.json",
        help="Output manifest file",
    )
    export_parser.set_defaults(func=cmd_export_manifest)

    # download
    download_parser = subparsers.add_parser(
        "download",
        help="Pre-download resources to cache",
    )
    download_parser.add_argument(
        "manifest",
        help="Manifest file",
    )
    download_parser.add_argument(
        "--cache-dir",
        help="Cache directory",
    )
    download_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Download timeout in seconds",
    )
    download_parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify SHA256 after download",
    )
    download_parser.set_defaults(func=cmd_download)

    # verify
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify cached resource integrity",
    )
    verify_parser.add_argument(
        "manifest",
        help="Manifest file",
    )
    verify_parser.add_argument(
        "--cache-dir",
        help="Cache directory",
    )
    verify_parser.set_defaults(func=cmd_verify)

    # audit
    audit_parser = subparsers.add_parser(
        "audit",
        help="Audit resource usage",
    )
    audit_parser.add_argument(
        "manifest",
        help="Manifest file",
    )
    audit_parser.add_argument(
        "--cache-dir",
        help="Cache directory",
    )
    audit_parser.add_argument(
        "--output",
        "-o",
        help="Output audit log file (JSON)",
    )
    audit_parser.set_defaults(func=cmd_audit)

    # offline-html
    offline_parser = subparsers.add_parser(
        "offline-html",
        help="Generate offline HTML with all resources inlined",
    )
    offline_parser.add_argument(
        "map",
        help="Map object (module:attr)",
    )
    offline_parser.add_argument(
        "--output",
        "-o",
        default="map_offline.html",
        help="Output HTML file",
    )
    offline_parser.set_defaults(func=cmd_offline_html)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """CLI 入口点。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
