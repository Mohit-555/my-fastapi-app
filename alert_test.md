# Alert API Test Guide

Use this with `rdpms_api_tester.html` and Base URL:

```text
http://localhost:8000
```

## Pagination

Pagination is implemented on the table-style Alert JSON APIs:

```text
GET /alerts/summary?page=1&page_size=50
GET /alerts/history?page=1&page_size=50
GET /alerts/events?page=1&page_size=50
```

Response metadata:

```json
{
  "total": 120,
  "page": 1,
  "page_size": 50,
  "total_pages": 3,
  "rows": []
}
```

For `/alerts/summary`, the response also has:

```json
{
  "total": 120,
  "total_rows": 24
}
```

Here `total` is total alert count and `total_rows` is total grouped summary rows.

## Pagination Test

1. Open `GET /alerts/history`.
2. Set `page=1` and `page_size=10`.
3. Click Send.
4. Confirm response has max 10 rows.
5. Set `page=2` and click Send.
6. Confirm response has the next rows and `page` is `2`.

Repeat for:

```text
GET /alerts/summary
GET /alerts/events
```

## Dependent Filter Test

Use:

```text
GET /alerts/live
GET /alerts/summary
GET /alerts/history
```

Test flow:

1. Select `zone_id`.
2. Confirm `division_id` shows only divisions under that zone.
3. Select `division_id`.
4. Confirm `station_id` shows only stations under that division.
5. Select `station_id`.
6. Select `alert_type`.
7. Select either `asset_type_hex` or `asset_type`.
8. Click Send.

Pass criteria:

```text
Request URL contains selected filters.
Response rows match selected filters.
Changing Zone clears Division and Station.
Changing Division clears Station.
Selecting Asset Group clears Asset Hex.
Selecting Asset Hex clears Asset Group.
```

## CSV Export

CSV endpoints are not paginated. They keep export `limit` behavior:

```text
GET /alerts/summary/download
GET /alerts/summary/export
GET /alerts/history/download?limit=5000
GET /alerts/history/export?limit=5000
```

## Endpoint Checklist

- [ ] `GET /alerts/filters`
- [ ] `GET /alerts/live`
- [ ] `GET /alerts/summary`
- [ ] `GET /alerts/summary/download`
- [ ] `GET /alerts/summary/export`
- [ ] `GET /alerts/history`
- [ ] `GET /alerts/history/download`
- [ ] `GET /alerts/history/export`
- [ ] `GET /alerts/events`
- [ ] `POST /alerts/events`
- [ ] `PUT /alerts/events/{event_id}`
- [ ] `POST /alerts/{event_id}/feedback`
- [ ] `POST /alerts/{event_id}/remark`
- [ ] `POST /alerts/{event_id}/acknowledge`
- [ ] `POST /alerts/{event_id}/rectification`
