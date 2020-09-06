import jinja2
import matplotlib
import matplotlib.pyplot as plt
import os
from pprint import PrettyPrinter
import pytz
import requests
import sqlite3

from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, render_template, request, send_file
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
from io import BytesIO
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas


################################################################################
## SETUP
################################################################################

app = Flask(__name__)

# Get the API key from the '.env' file
load_dotenv()
API_KEY = os.getenv("API_KEY")

# Settings for image endpoint
# Written with help from http://dataviztalk.blogspot.com/2016/01/serving-matplotlib-plot-that-follows.html
matplotlib.use("agg")
plt.style.use("ggplot")
pp = PrettyPrinter(depth=4)

my_loader = jinja2.ChoiceLoader(
    [
        app.jinja_loader,
        jinja2.FileSystemLoader("data"),
    ]
)
app.jinja_loader = my_loader


################################################################################
## ROUTES
################################################################################


@app.route("/")
def home():
    """Displays the homepage with forms for current or historical data."""
    context = {
        "min_date": (datetime.now() - timedelta(days=5)),
        "max_date": datetime.now(),
    }
    return render_template("home.html", **context)


def get_letter_for_units(units):
    """Returns a shorthand letter for the given units."""
    return "F" if units == "imperial" else "C" if units == "metric" else "K"


@app.route("/results")
def results():
    """Displays results for current weather conditions."""

    city = request.args.get("city")
    units = request.args.get("units")

    url = "http://api.openweathermap.org/data/2.5/weather"
    params = {"appid": API_KEY, "q": city, "units": units}

    result_json = requests.get(url, params=params).json()

    # Uncomment the line below to see the results of the API call!
    # pp.pprint(result_json)

    lat = result_json["coord"]["lat"]
    lon = result_json["coord"]["lon"]

    sunrise_time = get_zone_time(result_json["sys"]["sunrise"], lat, lon)
    sunset_time = get_zone_time(result_json["sys"]["sunset"], lat, lon)
    current_time = get_zone_time(datetime.now().timestamp(), lat, lon)

    context = {
        "date": current_time,
        "city": result_json["name"],
        "description": result_json["weather"][0]["description"],
        "temp": result_json["main"]["temp"],
        "humidity": result_json["main"]["humidity"],
        "wind_speed": result_json["wind"]["speed"],
        "sunrise": sunrise_time,
        "sunset": sunset_time,
        "units_letter": get_letter_for_units(units),
    }

    return render_template("results.html", **context)


def get_zone_time(date, lat, lon):
    """Adds a timezone value to a datetime from given location"""

    tf = TimezoneFinder()
    # get timezone string from latitude and longitude
    timezone_str = tf.timezone_at(lng=lon, lat=lat)
    # create pytz timezone object
    timezone = pytz.timezone(timezone_str)

    # create the time from the date object and add the timezone
    time = datetime.fromtimestamp(date).astimezone(timezone)

    return time


def get_min_temp(results):
    """Returns the minimum temp for the given hourly weather objects."""
    min = results[0]["temp"]
    for day in results:
        if day["temp"] < min:
            min = day["temp"]
    return min


def get_max_temp(results):
    """Returns the maximum temp for the given hourly weather objects."""
    max = results[0]["temp"]
    for day in results:
        if day["temp"] > max:
            max = day["temp"]
    return max


def get_lat_lon(city_name):
    geolocator = Nominatim(user_agent="Weather Application")
    location = geolocator.geocode(city_name)
    if location is not None:
        return location.latitude, location.longitude
    return 0, 0


@app.route("/historical_results")
def historical_results():
    """Displays historical weather forecast for a given day."""
    city = request.args.get("city")
    date = request.args.get("date")
    units = request.args.get("units")
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    date_in_seconds = int(date_obj.timestamp())
    latitude, longitude = get_lat_lon(city)

    url = "http://api.openweathermap.org/data/2.5/onecall/timemachine"
    params = {
        "lat": latitude,
        "lon": longitude,
        "units": units,
        "dt": date_in_seconds,
        "appid": API_KEY,
    }

    result_json = requests.get(url, params=params).json()

    # Uncomment the line below to see the results of the API call!
    pp.pprint(result_json)

    result_current = result_json["current"]
    result_hourly = result_json["hourly"]

    context = {
        "city": city,
        "date": date_obj,
        "lat": latitude,
        "lon": longitude,
        "units": units,
        "units_letter": get_letter_for_units(units),
        "description": result_current["weather"][0]["description"],
        "temp": result_current["temp"],
        "min_temp": get_min_temp(result_hourly),
        "max_temp": get_max_temp(result_hourly),
    }

    return render_template("historical_results.html", **context)


################################################################################
## IMAGES
################################################################################


def create_image_file(xAxisData, yAxisData, xLabel, yLabel):
    """
    Creates and returns a line graph with the given data.
    Written with help from http://dataviztalk.blogspot.com/2016/01/serving-matplotlib-plot-that-follows.html
    """
    fig, _ = plt.subplots()
    plt.plot(xAxisData, yAxisData)
    plt.xlabel(xLabel)
    plt.ylabel(yLabel)
    canvas = FigureCanvas(fig)
    img = BytesIO()
    fig.savefig(img)
    img.seek(0)
    return send_file(img, mimetype="image/png")


@app.route("/graph/<lat>/<lon>/<units>/<date>")
def graph(lat, lon, units, date):
    """
    Returns a line graph with data for the given location & date.
    @param lat The latitude.
    @param lon The longitude.
    @param units The units (imperial, metric, or kelvin)
    @param date The date, in the format %Y-%m-%d.
    """
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    date_in_seconds = date_obj.strftime("%s")

    url = "http://api.openweathermap.org/data/2.5/onecall/timemachine"
    params = {
        "appid": API_KEY,
        "lat": lat,
        "lon": lon,
        "units": units,
        "dt": date_in_seconds,
    }
    result_json = requests.get(url, params=params).json()

    hour_results = result_json["hourly"]

    hours = range(24)
    temps = [r["temp"] for r in hour_results]
    image = create_image_file(
        hours, temps, "Hour", f"Temperature ({get_letter_for_units(units)})"
    )
    return image


if __name__ == "__main__":
    app.run(debug=True)
