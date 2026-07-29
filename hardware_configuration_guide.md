# RDPMS Hardware Configuration Integration Guide

This guide describes the physical-to-logical hardware mapping hierarchy and outlines how the frontend should build the configuration screens, including which pages to create, the exact API request/response payloads, and step-by-step UI interaction workflows.

---

## 1. The Hardware Hierarchy Overview

To map real-world telemetry sensors to logical assets in the software, RDPMS uses the following hierarchy:

$$\text{Station} \longrightarrow \text{Master Card (Gateway)} \longrightarrow \text{Slave Cards} \longrightarrow \text{Channels (Pins)} \longrightarrow \text{Asset Parameter (Logical Alerting)}$$

1. **Master Card (Gateway)**: The main hardware unit (identified by `stngw_id` and `imei`) installed in the equipment room.
2. **Slave Cards**: Physical I/O cards (Voltage, Analog, DI, etc.) plugged into the Master Card slots. Each has a 1-byte hex address (e.g. `81`, `82`).
3. **Channels**: Physical screw terminals/ports on a Slave Card (e.g., `CH1` to `CH12`).
4. **Asset Parameter**: The logic linking a specific channel to a physical asset (e.g., *Point Machine PT-101 Current Sensor*) and a location box (`prloc`).

---

## 2. Configuration Pages & API Guide

For the frontend developer, we recommend implementing **three views/actions** under the Admin panel.

---

### Page A: Master Cards & Gateways (Listing & Linking)
* **Purpose**: View registered Master Cards (Gateways) and link them to their physical Station if not auto-assigned.
* **API Endpoints**:
  * **List all Master Cards**:
    * `GET /api/gateway/list`
    * **Response (`200 OK`)**:
      ```json
      [
        {
          "id": 1,
          "stngw_id": "456523AB",
          "imei": "867409070579912",
          "station_id": 5,
          "created_at": "2026-07-28T13:00:00.000000",
          "updated_at": "2026-07-28T14:30:00.000000",
          "gatewayId": 1,
          "stngwId": "456523AB",
          "stationId": 5
        },
        {
          "id": 2,
          "stngw_id": "12A34F56",
          "imei": "867409070582214",
          "station_id": null,
          "created_at": "2026-07-29T10:00:00.000000",
          "updated_at": "2026-07-29T10:00:00.000000",
          "gatewayId": 2,
          "stngwId": "12A34F56",
          "stationId": null
        }
      ]
      ```
  * **Link Master Card to Station**:
    * `POST /api/gateway/{stngw_id}/link-station`
    * **Response (`200 OK`)**:
      ```json
      {
        "id": 2,
        "stngw_id": "12A34F56",
        "imei": "867409070582214",
        "station_id": 8,
        "created_at": "2026-07-29T10:00:00.000000",
        "updated_at": "2026-07-29T10:45:00.000000",
        "gatewayId": 2,
        "stngwId": "12A34F56",
        "stationId": 8
      }
      ```
    * **Error Response (`422 Unprocessable Entity` - If Station code structure cannot be resolved)**:
      ```json
      {
        "detail": "Could not resolve a station for stngw_id '12A34F56'. Make sure the zone, division, and station exist in the database."
      }
      ```

#### 💡 UI Workflow & Click Actions (Page A)
1. **Initial Render**: The page performs a `GET /api/gateway/list` request and renders a table. Gateways where `station_id` is `null` should display a warning badge: `"Unlinked"`.
2. **User Clicks "Link Station" Button**:
   * **Action**: Trigger a `POST /api/gateway/{stngw_id}/link-station` call using the gateway's `stngw_id`.
   * **Frontend State Transition**:
     * Show a loading spinner on the button.
     * On Success: Replace the `"Unlinked"` badge with the newly returned station name/ID, display a toast notification `"Station linked successfully"`, and update the gateway object in the local state.
     * On Failure: Display an alert dialog containing the error detail returned by the backend (e.g. `"Zone/Station not found in database"`).

---

### Page B: Configure Slave Cards (Hardware Slots)
* **Purpose**: Manage the physical Slave Cards plugged into a selected Master Card.
* **UI Elements**:
  * Gateway selector dropdown.
  * Card list table.
  * "Add Card" modal.
* **API Endpoints**:
  * **List Slave Cards for a Gateway**:
    * `GET /api/slave-cards?gateway_id={gateway_id}`
    * **Response (`200 OK`)**:
      ```json
      {
        "total": 1,
        "page": 1,
        "page_size": 50,
        "total_pages": 1,
        "rows": [
          {
            "id": 1,
            "gateway_id": 5,
            "card_address": "81",
            "card_type": "Voltage",
            "created_at": "2026-07-28T13:00:00.000000",
            "gatewayId": 5,
            "cardAddress": "81",
            "cardType": "Voltage"
          }
        ]
      }
      ```
  * **Add a Slave Card**:
    * `POST /api/slave-cards`
    * **Request Body**:
      ```json
      {
        "gatewayId": 5,
        "cardAddress": "81",
        "cardType": "Voltage"
      }
      ```
    * **Response (`201 Created`)**:
      ```json
      {
        "id": 2,
        "gateway_id": 5,
        "card_address": "81",
        "card_type": "Voltage",
        "created_at": "2026-07-29T11:00:00.000000",
        "gatewayId": 5,
        "cardAddress": "81",
        "cardType": "Voltage"
      }
      ```
    * **Error Response (`409 Conflict` - Card address and type combination already exists)**:
      ```json
      {
        "detail": "Slave Card with address '81' and type 'Voltage' already configured under Gateway 5"
      }
      ```
  * **Update a Slave Card**:
    * `PUT /api/slave-cards/{id}`
    * **Request Body**:
      ```json
      {
        "cardAddress": "82",
        "cardType": "Analog"
      }
      ```
    * **Response (`200 OK`)**:
      ```json
      {
        "id": 2,
        "gateway_id": 5,
        "card_address": "82",
        "card_type": "Analog",
        "created_at": "2026-07-29T11:00:00.000000",
        "gatewayId": 5,
        "cardAddress": "82",
        "cardType": "Analog"
      }
      ```
  * **Delete a Slave Card**:
    * `DELETE /api/slave-cards/{id}`
    * **Response**: `204 No Content`
    * **Behavior**: Deletes the card and automatically unlinks/resets any mapped parameters to `null`.

#### 💡 UI Workflow & Click Actions (Page B)
1. **Select Gateway**: User selects a Gateway from a dropdown. This triggers a `GET /api/slave-cards?gateway_id={gateway_id}` request to populate the card list table.
2. **User Clicks "Add Slave Card"**:
   * **Action**: Opens a modal with inputs for **Card Address (Hex)** (e.g. `81`) and **Card Type Dropdown** (e.g. `Voltage`, `Analog`, `DI`).
   * **Submit Click**: Frontend sends `POST /api/slave-cards`.
   * **State Transition**:
     * Close the modal, show success toast `"Slave Card added successfully"`.
     * Append the new card object returned from the API response to the local `rows` state array so the table refreshes instantly without needing a full page reload.
3. **User Clicks "Edit"**:
   * **Action**: Populates the modal with the selected card's values and sends a `PUT /api/slave-cards/{id}` on submit. Updates the item in the local state array.
4. **User Clicks "Delete"**:
   * **Action**: Prompts the user with a confirmation warning: `"Deleting this Slave Card will reset all parameter channel assignments associated with it. Proceed?"`.
   * **Confirm Click**: Frontend triggers `DELETE /api/slave-cards/{id}`.
   * **State Transition**: Remove the card row from the local state array and show a success toast.

---

### Page C: Channel Assignment (Wiring Map Screen)
* **Purpose**: Complete the mapping by linking an incoming telemetry channel (which starts as *unassigned* when first detected) to its physical Slave Card, pin slot (`CH1`–`CH12`), target asset, and location box (`prloc`).
* **UI Elements**:
  * "Unassigned Channels" list.
  * Link modal containing:
    * Asset selector.
    * Location box input field (`prloc`).
    * Slave Card selector (populated from the selected Gateway).
    * Pin slot selector (`CH1` to `CH12`).
* **API Endpoints**:
  * **List Discovered Parameters / Channels**:
    * `GET /api/assets/parameters/configure`
    * *Optional Filters*: `is_assigned=false` (to see what needs configuration), `station_id`.
    * **Response (`200 OK`)**:
      ```json
      {
        "total": 1,
        "page": 1,
        "page_size": 50,
        "total_pages": 1,
        "rows": [
          {
            "id": 15,
            "para_id": "0001000C",
            "asset_id": null,
            "asset_number_code": null,
            "asset_type_hex": "00",
            "parameter_type_hex": "00",
            "parameter_name": "Voltage",
            "prloc": null,
            "is_assigned": false,
            "station_id": null,
            "station_code": null,
            "slave_card_id": null,
            "channel_number": null,
            "created_at": "2026-07-28T13:00:00.000000",
            "updated_at": "2026-07-28T13:00:00.000000",
            "slaveCardId": null,
            "channelNumber": null,
            "assetId": null,
            "assetNumberCode": null,
            "assetTypeHex": "00",
            "parameterTypeHex": "00",
            "parameterName": "Voltage",
            "stationId": null,
            "stationCode": null
          }
        ]
      }
      ```
  * **Link Channel to Slave Card & Asset**:
    * `PUT /api/assets/parameters/configure/{id}`
    * **Request Body**:
      ```json
      {
        "assetId": 12,
        "prloc": "LB-02",
        "slaveCardId": 1,
        "channelNumber": "CH3"
      }
      ```
    * **Response (`200 OK`)**:
      ```json
      {
        "id": 15,
        "para_id": "0001000C",
        "asset_id": 12,
        "asset_number_code": "PT-101",
        "asset_type_hex": "00",
        "parameter_type_hex": "00",
        "parameter_name": "Voltage",
        "prloc": "LB-02",
        "is_assigned": true,
        "station_id": 5,
        "station_code": "LKO",
        "slave_card_id": 1,
        "channel_number": "CH3",
        "created_at": "2026-07-28T13:00:00.000000",
        "updated_at": "2026-07-29T12:00:00.000000",
        "slaveCardId": 1,
        "channelNumber": "CH3",
        "assetId": 12,
        "assetNumberCode": "PT-101",
        "assetTypeHex": "00",
        "parameterTypeHex": "00",
        "parameterName": "Voltage",
        "stationId": 5,
        "stationCode": "LKO"
      }
      ```
  * **Delete/Reset Channel**:
    * `DELETE /api/assets/parameters/configure/{id}`
    * **Response**: `204 No Content`
    * **Behavior**: Permanently deletes this discovered parameter entry (will be auto-discovered again if telemetry packets for it continue to arrive).

#### 💡 UI Workflow & Click Actions (Page C)
1. **Initial Load**: Perform `GET /api/assets/parameters/configure?is_assigned=false` to display the list of parameters waiting to be wired and logically assigned.
2. **User Clicks "Configure" Button on a Parameter row**:
   * **Action**: Opens the Configuration Modal.
   * **Drop-downs Population**:
     * **Asset Selector**: Perform `GET /api/assets?station_id={station_id}` to load assets belonging to the same station.
     * **Slave Card Selector**: Perform `GET /api/slave-cards?gateway_id={gateway_id}` to load the cards configured for this gateway.
     * **Pin/Channel Selector**: Render static dropdown choices `CH1` to `CH12` (or card capacity limit).
     * **Location Box Input**: Text field for user input.
3. **Submit Click (Save Configuration)**:
   * **Action**: Sends `PUT /api/assets/parameters/configure/{id}` with the mapped selections.
   * **State Transition**:
     * Close the modal, show success toast `"Channel configuration saved successfully"`.
     * Remove the configured parameter row from the list of `"Unassigned Channels"` (since its `is_assigned` status is now `true`).
4. **User Clicks "Delete" / "Reset"**:
   * **Action**: Frontend issues a `DELETE /api/assets/parameters/configure/{id}` request.
   * **State Transition**: Removes the entry from the table instantly.
