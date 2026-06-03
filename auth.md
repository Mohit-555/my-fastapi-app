# Authentication API

This API uses two tokens:

- Access token: JWT used in the `Authorization` header for protected APIs.
- Refresh token: random long-lived token used to get a new access token.

Access tokens expire after `30` minutes. Refresh tokens expire after `1` day by default, or `7` days when `remember_me` is `true`.

## Protected APIs

Most API routers are protected by authentication. Send the access token in this header:

```http
Authorization: Bearer <access_token>
```

Public auth endpoints:

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /auth/logout`

Protected auth endpoint:

- `GET /auth/me`

## Register

Creates a new user account.

```http
POST /auth/register
Content-Type: application/json
```

Request body:

```json
{
  "full_name": "Demo User",
  "employee_id": "EMP001",
  "designation": "Engineer",
  "zone_id": null,
  "division_id": null,
  "mobile_number": "9876543210",
  "email": "demo@example.com",
  "password": "Password@123",
  "confirm_password": "Password@123",
  "reporting_officer_id": null
}
```

Success response: `201 Created`

```json
{
  "id": 1,
  "full_name": "Demo User",
  "employee_id": "EMP001",
  "designation": "Engineer",
  "zone_id": null,
  "division_id": null,
  "email": "demo@example.com",
  "mobile_number": "9876543210",
  "is_active": true,
  "created_at": "2026-06-03T10:00:00"
}
```

Common errors:

- `400`: Passwords do not match
- `400`: Employee ID already registered
- `400`: Email already registered

## Login

Verifies employee ID and password, then returns access and refresh tokens.

```http
POST /auth/login
Content-Type: application/json
```

Request body:

```json
{
  "employee_id": "EMP001",
  "password": "Password@123",
  "remember_me": true
}
```

Success response: `200 OK`

```json
{
  "access_token": "<jwt_access_token>",
  "refresh_token": "<refresh_token>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Notes:

- `expires_in` is in seconds.
- `remember_me: false` gives a 1-day refresh token.
- `remember_me: true` gives a 7-day refresh token.
- Only the hashed refresh token is stored in the database.

Common errors:

- `401`: Invalid employee ID or password
- `403`: Account is deactivated. Contact admin.

## Get Current User

Returns the logged-in user's profile from the access token.

```http
GET /auth/me
Authorization: Bearer <access_token>
```

Success response: `200 OK`

```json
{
  "id": 1,
  "full_name": "Demo User",
  "employee_id": "EMP001",
  "designation": "Engineer",
  "zone_id": null,
  "division_id": null,
  "email": "demo@example.com",
  "mobile_number": "9876543210",
  "is_active": true,
  "created_at": "2026-06-03T10:00:00"
}
```

Common errors:

- `401`: Invalid token
- `401`: Invalid or expired token
- `401`: User not found or inactive

## Refresh Token

Uses a valid refresh token to issue a new access token and a new refresh token.

```http
POST /auth/refresh
Content-Type: application/json
```

Request body:

```json
{
  "refresh_token": "<current_refresh_token>"
}
```

Success response: `200 OK`

```json
{
  "access_token": "<new_jwt_access_token>",
  "refresh_token": "<new_refresh_token>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

Important behavior:

- Refresh tokens rotate.
- After refresh succeeds, the old refresh token is revoked.
- Reusing the old refresh token returns `401`.
- The new refresh token keeps the original `remember_me` duration.

Common errors:

- `401`: Invalid or expired refresh token
- `401`: User not found or inactive

## Logout

Revokes the supplied refresh token.

```http
POST /auth/logout
Content-Type: application/json
```

Request body:

```json
{
  "refresh_token": "<current_refresh_token>"
}
```

Success response: `200 OK`

```json
{
  "message": "Logged out successfully"
}
```

Notes:

- Logout revokes the refresh token if it exists and is not already revoked.
- The response is still successful even if the token is already missing or revoked.
- The client should clear both access and refresh tokens after logout.

## Client Flow

Recommended frontend flow:

1. Call `POST /auth/login`.
2. Store `access_token` and `refresh_token`.
3. Send `Authorization: Bearer <access_token>` for protected APIs.
4. When the access token expires, call `POST /auth/refresh` with the current refresh token.
5. Replace both stored tokens with the tokens returned by `/auth/refresh`.
6. On logout, call `POST /auth/logout` with the current refresh token.
7. Clear both tokens locally.

## cURL Examples

Login:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"employee_id":"EMP001","password":"Password@123","remember_me":true}'
```

Call a protected API:

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Refresh:

```bash
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

Logout:

```bash
curl -X POST http://localhost:8000/auth/logout \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
```

## API Tester Notes

In `rdpms_api_tester.html`:

- Login saves both Access Token and Refresh Token.
- Refresh automatically inserts the saved refresh token into the request body.
- Logout automatically inserts the saved refresh token into the request body.
- Successful logout clears both saved tokens.
