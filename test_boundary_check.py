import folium
from folium import FeatureGroup, TileLayer
from folium.plugins import FeatureGroupSubGroup, MarkerCluster
from folium.map import _collect_controllable_layers

print('=== Test 1: Direct child layers are collected ===')
m = folium.Map(tiles=None)
l1 = TileLayer(name='Base1').add_to(m)
fg = FeatureGroup(name='Overlay1').add_to(m)
layers = _collect_controllable_layers(m)
print(f'Total layers: {len(layers)}')
labels = [info['label'] for info in layers.values()]
print(f'Labels: {labels}')
assert len(layers) == 2
assert 'Base1' in labels
assert 'Overlay1' in labels
print('PASSED\n')

print('=== Test 2: Nested layers inside control=True group are NOT collected (boundary) ===')
m2 = folium.Map(tiles=None)
outer = FeatureGroup(name='Outer', control=True).add_to(m2)
inner = FeatureGroup(name='Inner', control=True)
outer.add_child(inner)
layers2 = _collect_controllable_layers(m2)
print(f'Total layers: {len(layers2)}')
labels2 = [info['label'] for info in layers2.values()]
print(f'Labels: {labels2}')
assert len(layers2) == 1
assert 'Outer' in labels2
assert 'Inner' not in labels2
print('PASSED\n')

print('=== Test 3: control=False group is traversed, inner control=True layers collected ===')
m3 = folium.Map(tiles=None)
outer = FeatureGroup(name='Outer', control=False).add_to(m3)
inner = FeatureGroup(name='Inner', control=True)
outer.add_child(inner)
layers3 = _collect_controllable_layers(m3)
print(f'Total layers: {len(layers3)}')
labels3 = [info['label'] for info in layers3.values()]
print(f'Labels: {labels3}')
assert len(layers3) == 1
assert 'Outer' not in labels3
assert 'Inner' in labels3
print('PASSED\n')

print('=== Test 4: FeatureGroupSubGroup as direct child is collected ===')
m4 = folium.Map(tiles=None)
mcg = MarkerCluster(control=False).add_to(m4)
sg = FeatureGroupSubGroup(mcg, 'MySubGroup').add_to(m4)
layers4 = _collect_controllable_layers(m4)
print(f'Total layers: {len(layers4)}')
labels4 = [info['label'] for info in layers4.values()]
print(f'Labels: {labels4}')
assert len(layers4) == 1
assert 'MySubGroup' in labels4
print('PASSED\n')

print('=== Test 5: Same name layers both appear (unique internal keys) ===')
m5 = folium.Map(tiles=None)
a = TileLayer(name='Same').add_to(m5)
b = FeatureGroup(name='Same').add_to(m5)
layers5 = _collect_controllable_layers(m5)
print(f'Total layers: {len(layers5)}')
labels5 = [info['label'] for info in layers5.values()]
print(f'Labels: {labels5}')
assert len(layers5) == 2
assert labels5.count('Same') == 2
print('PASSED\n')

print('=== Test 6: Deduplication by object identity ===')
m6 = folium.Map(tiles=None)
fg1 = FeatureGroup(name='G1', control=False).add_to(m6)
fg2 = FeatureGroup(name='G2', control=False).add_to(m6)
shared = FeatureGroup(name='Shared', control=True)
fg1.add_child(shared)
fg2.add_child(shared)
layers6 = _collect_controllable_layers(m6)
print(f'Total layers: {len(layers6)}')
labels6 = [info['label'] for info in layers6.values()]
print(f'Labels: {labels6}')
assert len(layers6) == 1
assert 'Shared' in labels6
print('PASSED\n')

print('=== All tests passed! ===')
