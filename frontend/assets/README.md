# Map assets

Leaflet 1.9.4 is bundled under leaflet/ with its BSD license.
Source: https://unpkg.com/leaflet@1.9.4/dist/

Natural Earth 1:50m geography (public domain):
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson
Terms: https://www.naturalearthdata.com/about/terms-of-use/
map-base.js contains seven countries and all 27 Brazilian states in GeoJSON.

Detailed maps use https://tile.openstreetmap.org/{z}/{x}/{y}.png in the browser,
with visible attribution, standard browser caching and no bulk/offline downloads.
Policy: https://operations.osmfoundation.org/policies/tiles/
If tiles fail or the device is offline, local geography remains available.

Initial focus: southern Brazil and Maringa (-23.4205, -51.9386).
No official tornado corridor boundary is represented.
