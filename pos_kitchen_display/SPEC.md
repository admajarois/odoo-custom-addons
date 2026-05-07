# POS Kitchen Display - Odoo 19 Community

## Overview
Addons untuk mengirim pesanan dari POS ke kitchen display ketika mode restaurant/bar diaktifkan.

## Requirements
- Odoo 19 Community
- Konfigurasi POS dengan is_restaurant = True atau is_bar = True

## Features

### 1. Send to Kitchen Button (POS Frontend)
- Tombol "Send to Kitchen" muncul di POS screen
- Tombol hanya aktif ketika ada order line
- Jika is_restaurant atau is_bar aktif, tombol mengirim data ke kitchen

### 2. Kitchen Display Screen
- List order yang masuk dari POS
- Tampilkan: nama produk, quantity, meja, waktu order
- Tombol "Done" untuk menandai item selesai
- Tombol "Cancel" untuk membatalkan item
- Sound notification saat ada order baru

### 3. Data Flow
1. Kasir bikin order di POS → klik "Send to Kitchen"
2. Data order tersimpan di model `pos.kitchen.order`
3. Kitchen Display menampilkan order baru
4. Chef mark item sebagai "done" atau "cancel"

## Technical Specification

### Models
- `pos.kitchen.order` - Header order dari POS
- `pos.kitchen.order.line` - Line items yang perlu dimasak

### Fields - pos.kitchen.order
- name: Char (order reference)
- pos_order_id: Many2one ke pos.order
- table_id: Many2one ke pos.table
- order_date: Datetime
- state: Selection (pending, in_progress, done, cancelled)
- line_ids: One2many ke pos.kitchen.order.line

### Fields - pos.kitchen.order.line
- product_id: Many2one ke product.product
- product_name: Char
- quantity: Float
- note: Char (special instructions)
- state: Selection (pending, cooking, done, cancelled)
- order_id: Many2one ke pos.kitchen.order

### XML Views
- POS frontend widget untuk tombol Send to Kitchen
- Kitchen Display kanban/list view
- Kitchen Display action button

### JS Components
- KitchenDisplayScreen - Main screen di POS
- SendToKitchenButton - Widget tombol di order screen
- KitchenOrderLine - Component untuk menampilkan line

### RPC Methods
- send_to_kitchen(order_data) - Kirim order ke kitchen
- mark_done(order_line_id) - Mark item selesai
- cancel_item(order_line_id) - Cancel item

## User Scenario
1. Kasir buka POS → Pilih meja → Tambah produk → Klik "Send to Kitchen"
2. Di kitchen display, order baru muncul dengan sound beep
3. Chef masak item → Klik "Done" pada setiap item
4. Semua item done → Order di kitchen display selesai

## File Structure
```
pos_kitchen_display/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── pos_kitchen.py
├── views/
│   ├── pos_kitchen_views.xml
│   └── kitchen_menu.xml
├── static/
│   ├── src/
│   │   ├── js/
│   │   │   ├── kitchen_display.js
│   │   │   └── send_to_kitchen.js
│   │   └── css/
│   │       └── kitchen_display.css
│   └── description/
│       └── icon.png
```