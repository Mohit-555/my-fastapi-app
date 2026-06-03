# Threshold API

Threshold APIs manage warning and critical limits for asset telemetry parameters.

These APIs are protected. Send the access token in this header:

```http
Authorization: Bearer <access_token>
```

Thresholds can be configured as:

- Global defaults: `station_id` is `null`
- Station-specific overrides: `station_id` has a station ID

When telemetry needs a threshold, the API first checks for a station-specific threshold. If none exists, it uses the global default.

## Threshold Object

```json
{
  "id": 1,
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": null,
  "warning_low": null,
  "warning_high": 9.0,
  "critical_low": null,
  "critical_high": 11.0,
  "unit": "A",
  "description": "Point Machine Peak Current threshold",
  "created_at": "2026-06-03T10:00:00",
  "updated_at": "2026-06-03T10:00:00"
}
```

## List Thresholds

Returns configured thresholds. Optional filters can be used for asset type and station.

```http
GET /assets/thresholds
Authorization: Bearer <access_token>
```

Query parameters:

- `asset_type_hex`: optional asset type hex code
- `station_id`: optional station ID

Example:

```http
GET /assets/thresholds?asset_type_hex=00&station_id=1
```

Success response: `200 OK`

```json
[
  {
    "id": 1,
    "asset_type_hex": "00",
    "parameter_type_hex": "02",
    "station_id": 1,
    "warning_low": null,
    "warning_high": 9.0,
    "critical_low": null,
    "critical_high": 11.0,
    "unit": "A",
    "description": "Point Machine Peak Current threshold",
    "created_at": "2026-06-03T10:00:00",
    "updated_at": "2026-06-03T10:00:00"
  }
]
```

## Get Threshold

Returns one threshold by ID.

```http
GET /assets/thresholds/{threshold_id}
Authorization: Bearer <access_token>
```

Success response: `200 OK`

```json
{
  "id": 1,
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": null,
  "warning_low": null,
  "warning_high": 9.0,
  "critical_low": null,
  "critical_high": 11.0,
  "unit": "A",
  "description": "Point Machine Peak Current threshold",
  "created_at": "2026-06-03T10:00:00",
  "updated_at": "2026-06-03T10:00:00"
}
```

Common errors:

- `404`: Threshold not found

## Create Threshold

Creates a new threshold.

Use `station_id: null` for a global default. Use a station ID for a station-specific override.

```http
POST /assets/thresholds
Authorization: Bearer <access_token>
Content-Type: application/json
```

Request body:

```json
{
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": null,
  "warning_low": null,
  "warning_high": 9.0,
  "critical_low": null,
  "critical_high": 11.0,
  "unit": "A",
  "description": "Point Machine Peak Current threshold"
}
```

Success response: `201 Created`

```json
{
  "id": 1,
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": null,
  "warning_low": null,
  "warning_high": 9.0,
  "critical_low": null,
  "critical_high": 11.0,
  "unit": "A",
  "description": "Point Machine Peak Current threshold",
  "created_at": "2026-06-03T10:00:00",
  "updated_at": "2026-06-03T10:00:00"
}
```

Common errors:

- `400`: Unknown `asset_type_hex`
- `400`: Unknown `parameter_type_hex`
- `404`: Station not found
- `409`: Threshold already exists for this asset type, parameter type, and station

## Update Threshold

Updates threshold values by ID.

```http
PUT /assets/thresholds/{threshold_id}
Authorization: Bearer <access_token>
Content-Type: application/json
```

Request body:

```json
{
  "warning_high": 10.0,
  "critical_high": 12.0,
  "description": "Updated Point Machine Peak Current threshold"
}
```

Success response: `200 OK`

```json
{
  "id": 1,
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": null,
  "warning_low": null,
  "warning_high": 10.0,
  "critical_low": null,
  "critical_high": 12.0,
  "unit": "A",
  "description": "Updated Point Machine Peak Current threshold",
  "created_at": "2026-06-03T10:00:00",
  "updated_at": "2026-06-03T10:05:00"
}
```

Common errors:

- `404`: Threshold not found

## Delete Threshold

Deletes a threshold by ID.

```http
DELETE /assets/thresholds/{threshold_id}
Authorization: Bearer <access_token>
```

Success response: `204 No Content`

Common errors:

- `404`: Threshold not found

## Resolve Effective Threshold

Returns the effective threshold for an asset type and parameter type.

If `station_id` is supplied, the API returns the station-specific threshold when configured. Otherwise, it falls back to the global default.

```http
GET /assets/thresholds/resolve/{asset_type_hex}/{parameter_type_hex}
Authorization: Bearer <access_token>
```

Query parameters:

- `station_id`: optional station ID

Example:

```http
GET /assets/thresholds/resolve/00/02?station_id=1
```

Success response: `200 OK`

```json
{
  "id": 2,
  "asset_type_hex": "00",
  "parameter_type_hex": "02",
  "station_id": 1,
  "warning_low": null,
  "warning_high": 8.5,
  "critical_low": null,
  "critical_high": 10.5,
  "unit": "A",
  "description": "Station-specific Point Machine Peak Current threshold",
  "created_at": "2026-06-03T10:00:00",
  "updated_at": "2026-06-03T10:00:00"
}
```

If no threshold is configured, the response is `200 OK` with `null`.

```json
null
```

## Telemetry Usage

Telemetry APIs automatically include threshold values when a matching threshold is configured.

Example fields in telemetry responses:

```json
{
  "threshold_warning_low": null,
  "threshold_warning_high": 9.0,
  "threshold_critical_low": null,
  "threshold_critical_high": 11.0
}
```
