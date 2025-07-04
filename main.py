"""
The aim of this script is to retrieve all the GIS data about Italian roads available
on OSM.
For every value in the 'ref', 'nat_ref', 'name' tags 
 - a new layer is created
 - all matching segments are merged into it

 The tables are enriched with the tags
  - maxweight
  - maxwidth
  - maxaxleload
  - roadowner
  - owner_id
 
 TODO 
    OverPass API instead of quickosm
        -> recreate geometrie
        -> no layers
 """
import sys
from pathlib import Path
import overpy
import json
import time

BASE_DIR = Path("/home/psc/Desktop/Portfolio/Trasporti_Eccezionali/DB/QGIS")

# Relation ids to bound queries spatially
regions = {
    'Sicilia': 39152,
    'Puglia': 40095,
    'Basilicata': 40137,
    'Campania': 40218,
    'Lazio': 40784,
    'Molise': 41256,
    'Toscana': 41977,
    'Umbria': 42004,
    'Emilia-Romagna': 42611,
    'Veneto': 43648,
    'Piemonte': 44874,
    'Lombardia': 44879,
    'Valle d\'Aosta': 45155,
    'Trentino-Alto Adige': 45757,
    'Marche': 53060,
    'Abruzzo': 53937,
    'Friuli-Venezia Giulia': 179296,
    'Liguria': 301482,
    'Calabria': 1783980,
    'Sardegna': 7361997
}

highway_tags = [
    'motorway',
    'trunk',
    'primary',
    'secondary',
    'tertiary'
]

name_tags = [
    'ref',
    'nat_ref',
    'reg_ref',
    'alt_name'
]

DEFAULT_TAGS = {
    'maxheight': None,
    'maxweight': None,
    'maxwidth': None,
    'maxaxleload': None,
    'roadowner': None,
    'owner_id': None
}

def overpass_query(region, value):
    api = overpy.Overpass()
    query_region = f"""
        [out:json][timeout:25];
        area["ISO3166-1"="IT"][admin_level=2]->.italy;
        relation(area.italy)["admin_level"="4"]["name"={region}]["boundary"="administrative"];
        out ids;
    """

    # Extract the area ID for region
    try:
        result_region = api.query(query_region)
        if not result_region.relations:
            print(f"[WARNING] No relation found for region '{region}'")
            return None
        relation_id = result_region.relations[0].id
    except Exception as e:
        print(f"[ERROR] Failed to retrieve region '{region}': {e}")
        return None

    # The area ID for Overpass queries is 3600000000 + relation.id
    area_id = 3600000000 + relation_id

    # Step 2: Query all primary highways in the region
    query_highways = f"""
    [out:json][timeout:60];
    way["highway"={value}](area:{area_id});
    out body;
    out geom;
    """

    # Run the highway query
    result_highways = api.query(query_highways)
    # overpy result object has to be serialized for geojson output
    return result_highways

def save_geojson(ways, nodes, filepath):
    """
    Save a GeoJSON file with LineString features for ways and Point features for nodes.
    
    Args:
        ways (list): A list of overpy.Way objects.
        nodes (list): A list of overpy.Node objects.
        filename (str or Path): File path for the output .geojson
    """
    features = []

    # Build a dict of node_id → (lon, lat)
    node_dict = {node.id: (float(node.lon), float(node.lat)) for node in nodes}

    # Process ways
    for way in ways:
        coords = [node_dict[node.id] for node in way.nodes if node.id in node_dict]
        if len(coords) < 2:
            continue 

        tags = way.tags.copy()
        tags.update({k: v for k, v in DEFAULT_TAGS.items() if k not in tags})

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            },
            "properties": tags
        })

    # Process nodes (optional: only save those with tags or relevance)
    for node in nodes:
        tags = node.tags.copy()
        tags.update({k: v for k, v in DEFAULT_TAGS.items() if k not in tags})

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(node.lon), float(node.lat)]
            },
            "properties": tags
        })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "crs": {
            "type": "name",
            "properties": {
                "name": "urn:ogc:def:crs:OGC:1.3:CRS84"
            }
        }
    }

    with open(filepath, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"[INFO] Saved: {filepath}")



def find_names(overpass_result):
    road_names = set()
    for way in overpass_result.ways:
        for tag in name_tags:
            if tag in way.tags:
                road_names.add(way.tags[tag])
    return road_names


def extract_roads(names, region, tag, result):
    for name in names:
        # Filter ways that have this name in any of the name tags
        ways = []
        for way in result.ways:
            for name_tag in name_tags:
                if name_tag in way.tags and way.tags[name_tag] == name:
                    ways.append(way)
                    break  # No need to check other tags if we found a match
        if not ways:
            continue
        
        # Get all nodes referenced by these ways
        way_node_ids = set()
        for way in ways:
            way_node_ids.update(node.id for node in way.nodes)
        
        # Filter nodes that are either tagged with this name or part of these ways
        nodes = []
        for node in result.nodes:
            # Include if it's part of any way with this name
            if node.id in way_node_ids:
                nodes.append(node)
                continue
            # Or if it's directly tagged with this name
            for name_tag in name_tags:
                if name_tag in getattr(node, 'tags', {}) and node.tags[name_tag] == name:
                    nodes.append(node)
                    break

        # Save to file
        dir_path = BASE_DIR / Path(region) / tag
        safe_name = name.replace('/', '_').replace(' ', '_')
        file_name = f"{safe_name}.geojson"
        file_path = dir_path / file_name
        dir_path.mkdir(parents=True, exist_ok=True)
        save_geojson(ways, nodes, file_path)

def main():
    for region in regions:
        for tag in highway_tags:
            print(f"[INFO] Processing region '{region}', highway type '{tag}'")
            road_network = overpass_query(region, tag)
            if road_network is None:
                continue
            road_names = find_names(road_network)
            extract_roads(road_names, region, tag, road_network)
            time.sleep(5)
        time.sleep(15)


if __name__ == "__main__":
    main()
    

