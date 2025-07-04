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
        - rewrite functions to handle overpy result objects
        - remove QGIS and process logic
 """
import sys
from pathlib import Path
from qgis.core import (
    QgsProject,
    QgsFeatureRequest,
    QgsFields,
    QgsField,
    QgsFeature,
    QgsVectorFileWriter,
    QgsApplication
)
from qgis.analysis import QgsNativeAlgorithms
from qgis.core import QgsProcessingFeedback
from PyQt5.QtCore import QVariant
import pandas as pd
import overpy

QGIS_PYTHON_PATH = Path("/usr/share/qgis/python")  # Typical location for QGIS python modules on Linux
PROCESSING_PLUGIN_PATH = QGIS_PYTHON_PATH / "plugins"

# Add paths to sys.path (convert Path to str)
sys.path.append(str(QGIS_PYTHON_PATH))
sys.path.append(str(PROCESSING_PLUGIN_PATH))
BASE_DIR = Path("/home/psc/Desktop/Portfolio/Trasporti_Eccezionali/DB/QGIS")

# Relation ids to bound queries spatially
regions = {
    'Sicilia': 39152
    'Puglia': 40095
    'Basilicata': 40137
    'Campania': 40218
    'Lazio': 40784
    'Molise': 41256
    'Toscana': 41977
    'Umbria': 42004
    'Emilia-Romagna': 42611
    'Veneto': 43648
    'Piemonte': 44874
    'Lombardia': 44879
    'Valle d\'Aosta': 45155
    'Trentino-Alto Adige': 45757
    'Marche': 53060
    'Abruzzo': 53937
    'Friuli-Venezia Giulia': 179296
    'Liguria': 301482
    'Calabria': 1783980
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


def overpass_query(region, value):
    api = overpy.Overpass()
    query_region = f"""
        [out:json][timeout:25];
        area["ISO3166-1"="IT"][admin_level=2]->.italy;
        relation(area.italy)["admin_level"="4"]["name"={region}]["boundary"="administrative"];
        out ids;
    """
    result_region = api.query(query_region)

    # Extract the area ID for Toscana
    # The area ID for Overpass queries is 3600000000 + relation.id
    relation_id = result_region.relations[0].id
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

def serialize_overpass_result(result):
    serializable_data = {
        "ways": [],
        "nodes": [],
        "relations": []
    }
    
    # Convert ways to serializable format
    for way in result.ways:
        serializable_data["ways"].append({
            "id": way.id,
            "nodes": [node.id for node in way.nodes],
            "tags": way.tags
        })
    
    # Convert nodes to serializable format
    for node in result.nodes:
        serializable_data["nodes"].append({
            "id": node.id,
            "lat": float(node.lat),
            "lon": float(node.lon),
            "tags": node.tags if hasattr(node, 'tags') else {}
        })
    
    # Convert relations to serializable format (if needed)
    for relation in result.relations:
        serializable_data["relations"].append({
            "id": relation.id,
            "tags": relation.tags,
            "members": [{
                "type": member.type,
                "ref": member.ref,
                "role": member.role
            } for member in relation.members]
        })
    return serializable_data

def save_geojson(result, filename):
    serialized_result = serialize_overpass_result(result)
    with open(filename, "w") as f:
        json.dump(serialized_result, f, indent=2)


def find_names(overpass_result):
    road_names = set()
    for way in enumerate(overpass_result.ways):
        for tag in name_tags:
            try:
                value = way.tags['highway']
            except:
                pass
            if value:
                road_names.add(value, tag)
    return road_names

def extract_roads(names, region, result):
    for name in names:
        # Filter ways that have this name in any of the name tags
        ways = []
        for way in result.ways:
            for tag in name_tags:
                if tag in way.tags and way.tags[tag] == name:
                    ways.append(way)
                    break  # No need to check other tags if we found a match
        
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
            for tag in name_tags:
                if tag in getattr(node, 'tags', {}) and node.tags[tag] == name:
                    nodes.append(node)
                    break
        
        # Create a new result-like structure
        new_road = {
            "ways": ways,
            "nodes": nodes,
            "relations": []  # You can add relation filtering if needed
        }
        
        # Save to file
        dir_path = Path(region) / name
        file_name = f"{name}.gpkg"  # Fixed the filename to use actual name
        file_path = dir_path / file_name
        dir_path.mkdir(parents=True, exist_ok=True)
        save_geojson(new_road, file_path)

def main():
    QGIS_PREFIX_PATH = "/usr"
    qgs = QgsApplication([], False)
    qgs.setPrefixPath(QGIS_PREFIX_PATH, True)
    qgs.initQgis()

   
    from processing.core.Processing import Processing

    Processing.initialize()
    qgs.processingRegistry().addProvider(QgsNativeAlgorithms())

    for region in regions:
        road_network = download_data(region)
        for layer in road_network:
            extract_roads(layer)

    qgs.exitQgis()

if __name__ == "__main__":
    main()
    

