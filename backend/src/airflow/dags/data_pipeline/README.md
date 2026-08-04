# Attraction crawler DAGs

This folder exposes four Airflow DAGs that share the same seven-stage pipeline.

| DAG | Sources | Schedule |
| --- | --- | --- |
| `osm_wikimedia_attractions_pipeline` | OpenStreetMap, Wikipedia, Wikidata | Weekly |
| `google_maps_poc_attractions_pipeline` | Rendered public Google Maps result cards through Playwright; no Maps API | Manual |
| `booking_agoda_attractions_pipeline` | Booking.com and/or Agoda public pages | Manual |
| `combined_attractions_pipeline` | Both source families, followed by cross-source deduplication | Manual |

## Pipeline blocks

Each single-source DAG exposes these task IDs in the Airflow graph:

| Diagram block | Airflow task | Responsibility |
| --- | --- | --- |
| 1. Data Source | `data_source` | Resolve the Vietnam destination boundary or coordinate radius and prepare its database identity. |
| 2. Extract | `extract` | Read public source candidates without mapping them to the database schema. |
| 3. Validate & Clean | `validate_clean` | Enforce geography, source eligibility, and clean display names. |
| 4. Normalize | `normalize` | Map valid candidates into the canonical `attractions` record; source enrichment happens here. |
| 5. Deduplicate | `deduplicate` | Apply shared duplicate rules and category-balanced selection. |
| 6. Load to PostgreSQL | `load_to_postgresql` | Upsert canonical records into the primary PostgreSQL database. |
| 7. Quality Check | `quality_check` | Publish schema validity plus description, image, category, and source coverage metrics through XCom. |

The combined DAG uses parallel `*_osm` and `*_ota` variants for blocks 2 through
4, then joins them at the shared `deduplicate`, `load_to_postgresql`, and
`quality_check` blocks.

## Destination parameters

- `destination_name` is always required and must name a destination in Vietnam.
- If `location_coords` contains `latitude,longitude`, those coordinates are
  authoritative. Records must fall within `radius_meters`.
- If `location_coords` is empty, the crawler resolves an administrative polygon
  for `destination_name`. Records without a verifiable coordinate, or outside
  that polygon, are rejected.
- `item_limit` is applied after geographic filtering, deduplication, and category
  balancing.

## Diversity and deduplication policy

- OSM tags are authoritative for broad categories such as museums, nature,
  entertainment, and restaurants; text classification is the fallback.
- The OSM collector normalizes and deduplicates the complete bounded Overpass
  response before choosing a category-balanced enrichment pool. This prevents
  the attraction portion of the response from excluding later food records.
- Records with the same source ID are duplicates. Physical non-tour records are
  also merged when their canonical names are equal or strongly similar and their
  coordinates are within 300 metres. Tour products additionally require matching
  duration and address.
- When multiple categories are available, selection initially limits each one to
  40% of `item_limit`. The cap is soft: if the available mix cannot fill the
  requested limit, remaining slots are distributed starting with the currently
  least-represented category.

The combined DAG intentionally uses the same prepared destination context for
both collectors. This prevents one source from using a radius while another uses
a similarly named but different administrative region.

## Google Maps POC scraping

The Google Maps DAG is a manually triggered proof of concept. It uses the
Playwright Chromium runtime already installed in the custom Airflow image and
does not require a Google Maps or Places API key. It reads rendered search cards,
does not log in, does not bypass CAPTCHA or access challenges, and stops with a
clear error when Google presents a challenge.

Attraction searches request the Vietnamese interface and retain only names with
Vietnamese characters. Restaurants and cafes keep their public display names.
Every result must still pass the shared coordinate radius or administrative
boundary check before it can be loaded.

## OTA web scraping

The OTA DAGs are manual and disabled by default because Booking.com and Agoda
restrict automated extraction in their terms. Triggering either OTA path requires
`allow_ota_web_scraping=true` or the container environment variable
`ALLOW_OTA_WEB_SCRAPING=true`.

The scraper:

- reads only public pages;
- does not log in or call Agoda's private GraphQL endpoint;
- does not bypass CAPTCHA or access challenges;
- stops on repeated blocking responses;
- uses one browser/request stream per source with delays;
- stores aggregate ratings only, not review text.

Booking pages are parsed from their public HTML. Agoda activity pages are rendered
with Playwright Chromium because their product content is client-rendered. The
custom Airflow image installs that browser runtime.

## Runtime configuration

Database values can be overridden with `VSF_DB_NAME`, `VSF_DB_USER`,
`VSF_DB_PASSWORD`, `VSF_DB_HOST`, and `VSF_DB_PORT`. Set
`VSF_CRAWLER_CONTACT` to a monitored email address for the crawler user agent.

Build and start Airflow from the `airflow` directory so the custom image is used:

```powershell
docker compose build
docker compose up -d
```

Pure parser and selection tests do not require Airflow or network access:

```powershell
python -m unittest discover -s airflow/tests -v
```
