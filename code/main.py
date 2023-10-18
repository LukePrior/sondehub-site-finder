import json
from datetime import datetime
import mgrs
import pyproj
import requests


MGRS_PRECISION = 2 # 5: 1m, 4: 10m, 3: 100m, 2: 1km, 1: 10km, 0: 100km
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


def get_sondehub_sites():
    """
    Download sites list from SondeHub API.
    """

    response = requests.get("https://api.v2.sondehub.org/sites")
    response.raise_for_status()
    return response.json()

def filter_raw_predictions():
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

def prediction_stats(predictions):
    """
    Print out some stats about the predictions.
    """

    print("Total predictions: {}".format(len(predictions)))


def filter_predictions(predictions, areas=[]):
    """
    Given a list of predictions filter out the ones that are in the provided areas (lat_min	lat_max	lon_min	lon_max).
    """

    filtered = {}

    for prediction in predictions.values():
        remove_prediction = False
        for area in areas:
            if prediction.prediction["lat"] > area[0] and prediction.prediction["lat"] < area[1] and prediction.prediction["lon"] > area[2] and prediction.prediction["lon"] < area[3]:
                remove_prediction = True
                break
        if not remove_prediction:
            filtered[prediction.id] = prediction

    return filtered


def filter_assigned_predictions(predictions, sondehub_sites, radius=3000):
    """
    Given a list of predictions filter out the ones that are within an x metre radius of a launch site.
    """

    filtered = {}

    for prediction in predictions.values():
        remove_prediction = False
        for site in sondehub_sites:
            location = sondehub_sites[site]["position"]
            if geod.line_length([prediction.prediction["lon"], location[0]], [prediction.prediction["lat"], location[1]]) < radius:
                remove_prediction = True
                break
        if not remove_prediction:
            filtered[prediction.id] = prediction

    return filtered


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


def filter_grids(grid, threshold=None, limit=None):
    """
    Return a list of grids of length limit with a count above the threshold or highest count if threshold is None.
    """

    grids = []

    for grid, data in grid.items():
        if threshold is None or data["count"] >= threshold:
            grids.append((grid, data["count"]))

    grids.sort(key=lambda x: x[1], reverse=True)

    return grids[:limit]


def get_grid_estimated_launch(target_grid, predictions):
    """
    Return the avergae position of all the predictions in the grid.
    """

    lat_sum = 0
    lon_sum = 0
    count = 0

    for prediction in predictions.values():
        if prediction.grid == target_grid:
            lat_sum += prediction.prediction["lat"]
            lon_sum += prediction.prediction["lon"]
            count += 1

    lat_avg = round(lat_sum / count, 7)
    lon_avg = round(lon_sum / count, 7)

    return [lat_avg, lon_avg]


def generate_geojson(grid, predictions, target_grid):
    """
    Generate a geojson file with all the bounding boxes.
    """

    geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    for grid, data in grid.items():
        if grid != target_grid:
            continue

        # add a bounding box for each grid
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
                        "coordinates": [round(prediction.prediction["lon"], 7), round(prediction.prediction["lat"], 7)]
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

        # add a marker for the estimated launch site
        lat_avg, lon_avg = get_grid_estimated_launch(grid, predictions)
        geojson["features"].append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon_avg, lat_avg]
            },
            "properties": {
                "id": "estimated",
                "serial": "estimated",
                "type": "estimated",
                "subtype": "estimated",
                "datetime": "estimated",
                "alt": "estimated",
                "launch_site": "estimated"
            }
        })


    with open('results/geojson-{}.json'.format(target_grid), 'w') as f:
        json.dump(geojson, f)


if __name__ == "__main__":
    sondehub_sites = get_sondehub_sites()
    predictions = read_predictions('data/filtered.json')
    predictions = filter_predictions(predictions, areas=[(29.4533796, 33.3356317, 34.2674994, 35.8950234)])
    predictions = filter_assigned_predictions(predictions, sondehub_sites)
    grid = assign_grid(predictions)
    top = filter_grids(grid, threshold=10)
    for grid_id, count in top:
        generate_geojson(grid, predictions, grid_id)