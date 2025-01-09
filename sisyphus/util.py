import json
import logging
import urllib.request
import urllib.error


def download(url, path):
    """
    Download a file and save it.
    """
    logging.debug("Downloading '%s'", url)
    try:
        with urllib.request.urlopen(url) as response, open(path, 'wb') as out_file:
            out_file.write(response.read())
    except urllib.error.HTTPError as e:
        logging.error("HTTP Error: %s - %s", e.code, e.reason)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        logging.error("URL Error: %s", e.reason)
        raise SystemExit(1)
    # TODO More exceptions (file)?


def query_api(url):
    """
    Query an API and return the JSON structure.
    """
    logging.debug("Querying '%s'", url)
    try:
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logging.error("HTTP Error: %s - %s", e.code, e.reason)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        logging.error("URL Error: %s", e.reason)
        raise SystemExit(1)
