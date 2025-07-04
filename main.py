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

def extract_roads(input_layer, region):
    csv_path = "custom_table.csv"
    df = pd.read_csv(csv_path)
    custom_field_names = df.columns.tolist()

    output_fields = QgsFields()
    existing_field_names = [field.name() for field in input_layer.fields()]
    for field in input_layer.fields():
        output_fields.append(field)

    for name in custom_field_names:
        if name not in existing_field_names:
            output_fields.append(QgsField(name, QVariant.String)) 
    
    geometry_type = input_layer.wkbType()
    crs = input_layer.crs()

    road_names = find_names(input_layer)
    for (value, tag) in road_names:

        dir_path = Path(region) / value
        file_name = f"{tag}_{geometry_type}.gpkg"
        file_path = dir_path / file_name
        dir_path.mkdir(parents=True, exist_ok=True)
        layer_name = f"{value}_{tag}"
        writer = QgsVectorFileWriter.create(
            str(file_path),
            output_fields,
            geometry_type,
            crs,
            "utf-8",
            driverName="GPKG",
            layerName=layer_name
        )

        expression = f'{tag} = \'{value}\''
        request = QgsFeatureRequest().setFilterExpression(expression)

        for feature in input_layer.getFeatures(request):
            new_feat = QgsFeature()
            new_feat.setGeometry(feature.geometry())
            # Get original attributes as a dictionary
            attr_dict = dict(zip(existing_field_names, feature.attributes()))
            # Prepare extended attributes
            new_attrs = [attr_dict.get(name, None) for name in existing_field_names]
            extra_attrs = [attr_dict.get(name, None) if name in attr_dict else None for name in custom_field_names if name not in existing_field_names]
            new_feat.setAttributes(new_attrs + extra_attrs)
            writer.addFeature(new_feat)

        # Cleanup
        del writer

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
    

