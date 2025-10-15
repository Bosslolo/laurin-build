## 2025.10.08 — Database Snapshot Release

This release captures the current active database and the latest UI/UX updates, so downloading and starting on a laptop preserves all current data.

### Added
- `database_backup_cmd.sql`
- `database_backup_final.sql`
- `database_backup_ps.sql`
- `Backups/database_backup_final_utf8.sql`
- `app/static/css/global.css`
- `app/static/js/main/user_search.js`
- `app/templates/entries.html.backup2`

### Modified
- `app/routes.py`
- `app/static/css/entries.css`
- `app/static/css/index.css`
- `app/static/js/entries.js`
- `app/static/js/index.js`
- `app/static/js/main/pin_auth.js`
- `app/templates/admin_access_logs.html`
- `app/templates/admin_display_items.html`
- `app/templates/admin_encoding_fixes.html`
- `app/templates/admin_login.html`
- `app/templates/entries.html`
- `app/templates/index.html`
- `app/templates/monthly_report.html`
- `app/templates/price_list.html`
- `app/templates/security_gate.html`

### How to Restore the Database (Laptop)
1. Start the environment:
   ```bash
   ./start_laptop.sh
   ```
2. Wait ~15–30 seconds for the DB to be ready.
3. Import one of the backups (pick the most recent):
   ```bash
   docker exec -i laurin_build_db psql -U user -d db < database_backup_final.sql
   ```
   If importing from `Backups/database_backup_final_utf8.sql`:
   ```bash
   docker exec -i laurin_build_db psql -U user -d db < Backups/database_backup_final_utf8.sql
   ```
4. Verify via Adminer: http://localhost:8080

### Notes
- These `.sql` files were intentionally added even if matched by `.gitignore`.
- Consider Git LFS for large backups in future releases.


