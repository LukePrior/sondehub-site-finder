import json
from datetime import datetime
import mgrs
import pyproj


MGRS_PRECISION = 3 # 5: 1m, 4: 10m, 3: 100m, 2: 1km, 1: 10km, 0: 100km
MGRS_SIZE = 10 ** (5 - MGRS_PRECISION)

mgrs = mgrs.MGRS()
geod = pyproj.Geod(ellps='WGS84')

class Prediction:
    def __init__(self, prediction):
        self.id = prediction["_id"]
        self.serial = prediction["_source"]["serial"]
        self.type = prediction["_source"]["type"]
        self.subtype = prediction["_source"]["subtype"]
        self.prediction = {
            "lat": prediction["_source"]["data"][-1]["lat"], 
            "lon": prediction["_source"]["data"][-1]["lon"], 
            "alt": prediction["_source"]["data"][-1]["alt"], 
            "datetime": datetime.fromtimestamp(prediction["_source"]["data"][-1]["time"])
        }
        self.launch_site = prediction["_source"]["launch_site"] if "launch_site" in prediction["_source"] else None
        self.grid = None

    def assign_grid(self, MGRSPrecision=MGRS_PRECISION):
        """
        Assign the appropriate grid to the prediction given the size of the grid.
        """

        self.grid = mgrs.toMGRS(self.prediction["lat"], self.prediction["lon"], MGRSPrecision=MGRSPrecision)


def filter_predictions():
    """
    Only include predictions without an assigned launch site.
    """

    filtered = open('data/filtered.json', 'w')

    with open('data/raw.json', 'r') as f:
        for row in f:
            prediction = json.loads(row)
            if "launch_site" not in prediction["_source"]:
                filtered.write(row)

    filtered.close()


def read_predictions(file_name):
    """
    Given a raw file import the predictions.
    """

    predictions = {}
    seen = set()

    with open(file_name, 'r') as f:
        for row in f:
            prediction = json.loads(row)
            if prediction["_source"]["serial"] in seen:
                continue
            seen.add(prediction["_source"]["serial"])
            prediction = Prediction(prediction)
            predictions[prediction.id] = prediction

    return predictions


def assign_grid(predictions, MGRSPrecision=MGRS_PRECISION):
    """
    Given a list of predictions assign them to a grid.
    """

    grid = {}

    for prediction in predictions.values():
        prediction.assign_grid(MGRSPrecision)

        if prediction.grid not in grid:
            lat_min, lon_min = mgrs.toLatLon(prediction.grid)

            x_var = geod.line_length([lon_min, lon_min], [lat_min, lat_min + 1])
            y_var = geod.line_length([lon_min, lon_min + 1], [lat_min, lat_min])

            lat_max = lat_min + MGRS_SIZE / x_var
            lon_max = lon_min + MGRS_SIZE / y_var

            grid[prediction.grid] = {
                "count": 0,
                "lat_min": round(lat_min, 6),
                "lat_max": round(lat_max, 6),
                "lon_min": round(lon_min, 6),
                "lon_max": round(lon_max, 6)
            }

        grid[prediction.grid]["count"] += 1
    
    return grid


def get_most_common_grid(grid):
    """
    Given a grid return the most common grid.
    """

    max_count = 0
    max_grid = None

    for grid, data in grid.items():
        if data["count"] > max_count:
            max_count = data["count"]
            max_grid = grid

    return max_grid


def generate_geojson(grid, predictions, target_grid=None):
    """
    Generate a geojson file with all the bounding boxes.
    """

    geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    for grid, data in grid.items():
        if target_grid is not None and grid != target_grid:
            continue
        geojson["features"].append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [data["lon_min"], data["lat_min"]],
                    [data["lon_min"], data["lat_max"]],
                    [data["lon_max"], data["lat_max"]],
                    [data["lon_max"], data["lat_min"]],
                    [data["lon_min"], data["lat_min"]]
                ]]
            },
            "properties": {
                "count": data["count"]
            }
        })

        # add a marker for each prediction in the grid
        for prediction in predictions.values():
            if prediction.grid == grid:
                geojson["features"].append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [prediction.prediction["lon"], prediction.prediction["lat"]]
                    },
                    "properties": {
                        "id": prediction.id,
                        "serial": prediction.serial,
                        "type": prediction.type,
                        "subtype": prediction.subtype,
                        "datetime": prediction.prediction["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                        "alt": prediction.prediction["alt"],
                        "launch_site": prediction.launch_site
                    }
                })

    with open('data/geojson.json', 'w') as f:
        json.dump(geojson, f)


if __name__ == "__main__":
    predictions = read_predictions('data/filtered.json')
    grid = assign_grid(predictions)
    generate_geojson(grid, predictions, get_most_common_grid(grid))