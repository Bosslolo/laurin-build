#!/usr/bin/env python3
"""
Automatic Monthly Backup Generator
This script can be run via cron to automatically generate monthly backup CSVs.

Usage:
    python generate_monthly_backup.py [year] [month]
    
    If year/month not provided, defaults to previous month.
    
Cron example (runs on 1st of each month at 2 AM):
    0 2 1 * * cd /path/to/laurin-build && python generate_monthly_backup.py
"""

import sys
import os
from datetime import date, datetime
from pathlib import Path

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import consumptions, users, beverages, roles
from sqlalchemy import func
import csv

def generate_monthly_backup(year=None, month=None):
    """Generate monthly backup files for the specified month."""
    
    # Determine target month
    if not year or not month:
        today = date.today()
        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1
    
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    print(f"Generating backup for {start_date.strftime('%Y-%m')}...")
    print(f"Period: {start_date} to {end_date}")
    
    # Create Flask app context
    app = create_app()
    with app.app_context():
        # Create backup directory
        backup_dir = Path("CSV For each month")
        backup_dir.mkdir(exist_ok=True)
        
        # Generate detailed backup
        print("Fetching detailed consumption records...")
        detailed_records = db.session.query(
            consumptions.id,
            consumptions.user_id,
            users.first_name,
            users.last_name,
            users.email,
            users.itsl_id,
            roles.name.label('role_name'),
            consumptions.beverage_id,
            beverages.name.label('beverage_name'),
            beverages.category,
            consumptions.quantity,
            consumptions.unit_price_cents,
            consumptions.invoice_id,
            consumptions.beverage_price_id,
            consumptions.created_at
        ).join(users, consumptions.user_id == users.id)\
         .join(roles, users.role_id == roles.id)\
         .join(beverages, consumptions.beverage_id == beverages.id)\
         .filter(
             consumptions.created_at >= start_date,
             consumptions.created_at < end_date
         )\
         .order_by(consumptions.created_at, consumptions.id)\
         .all()
        
        print(f"Found {len(detailed_records)} consumption records")
        
        # Write detailed backup CSV
        detailed_filename = backup_dir / f"consumption_backup_{start_date.strftime('%Y_%m')}.csv"
        print(f"Writing detailed backup to {detailed_filename}...")
        
        with open(detailed_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            writer.writerow(['# BACKUP FILE - Detailed Consumption Records'])
            writer.writerow(['# Generated:', datetime.now().isoformat()])
            writer.writerow(['# Period:', f"{start_date} to {end_date}"])
            writer.writerow(['# Total Records:', len(detailed_records)])
            writer.writerow([])
            
            writer.writerow([
                'CONSUMPTION_ID', 'USER_ID', 'USER_FIRST_NAME', 'USER_LAST_NAME',
                'USER_EMAIL', 'USER_ITSL_ID', 'USER_ROLE', 'BEVERAGE_ID',
                'BEVERAGE_NAME', 'BEVERAGE_CATEGORY', 'QUANTITY', 'UNIT_PRICE_CENTS',
                'TOTAL_COST_CENTS', 'INVOICE_ID', 'BEVERAGE_PRICE_ID', 'CREATED_AT'
            ])
            
            for record in detailed_records:
                total_cost_cents = record.quantity * record.unit_price_cents
                writer.writerow([
                    record.id, record.user_id, record.first_name, record.last_name,
                    record.email or '', record.itsl_id or '', record.role_name,
                    record.beverage_id, record.beverage_name, record.category,
                    record.quantity, record.unit_price_cents, total_cost_cents,
                    record.invoice_id, record.beverage_price_id,
                    record.created_at.isoformat()
                ])
        
        print(f"✅ Detailed backup saved: {detailed_filename}")
        
        # Generate aggregated report
        print("Generating aggregated report...")
        aggregated_data = db.session.query(
            users.first_name,
            users.last_name,
            users.email,
            roles.name.label('role_name'),
            beverages.name.label('beverage_name'),
            beverages.category,
            func.sum(consumptions.quantity).label('total_quantity'),
            func.count(consumptions.id).label('consumption_count'),
            func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_cost_cents'),
            func.avg(consumptions.unit_price_cents).label('avg_price_cents')
        ).join(roles, users.role_id == roles.id)\
         .join(consumptions, users.id == consumptions.user_id)\
         .join(beverages, consumptions.beverage_id == beverages.id)\
         .filter(
             consumptions.created_at >= start_date,
             consumptions.created_at < end_date
         )\
         .group_by(users.id, users.first_name, users.last_name, users.email, roles.name, beverages.id, beverages.name, beverages.category)\
         .order_by(users.last_name, users.first_name, beverages.name)\
         .all()
        
        # Write aggregated report CSV
        report_filename = backup_dir / f"consumption_report_{start_date.strftime('%Y_%m')}.csv"
        print(f"Writing aggregated report to {report_filename}...")
        
        with open(report_filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            writer.writerow(['# MONTHLY CONSUMPTION REPORT - Aggregated Data'])
            writer.writerow(['# Generated:', datetime.now().isoformat()])
            writer.writerow(['# Period:', f"{start_date} to {end_date}"])
            writer.writerow(['# Report Date:', start_date.strftime('%Y-%m')])
            writer.writerow(['# Total Users:', len(set((c.first_name, c.last_name) for c in aggregated_data))])
            writer.writerow([])
            
            writer.writerow(['USER', 'BEVERAGE', 'CATEGORY', 'QUANTITY', 'ORDERS', 'AVG PRICE', 'TOTAL COST'])
            
            for consumption in aggregated_data:
                user_name = f"{consumption.first_name} {consumption.last_name}"
                avg_price_euros = consumption.avg_price_cents / 100.0
                total_cost_euros = consumption.total_cost_cents / 100.0
                
                writer.writerow([
                    user_name,
                    consumption.beverage_name,
                    consumption.category.title(),
                    consumption.total_quantity,
                    consumption.consumption_count,
                    f"€{avg_price_euros:.2f}",
                    f"€{total_cost_euros:.2f}"
                ])
        
        print(f"✅ Aggregated report saved: {report_filename}")
        print(f"\n✅ Backup generation complete!")
        print(f"   Period: {start_date.strftime('%Y-%m')}")
        print(f"   Records: {len(detailed_records)}")
        print(f"   Users: {len(set((c.first_name, c.last_name) for c in aggregated_data))}")
        
        return {
            "success": True,
            "detailed_backup": str(detailed_filename),
            "aggregated_report": str(report_filename),
            "records": len(detailed_records)
        }

if __name__ == "__main__":
    year = None
    month = None
    
    if len(sys.argv) > 1:
        year = int(sys.argv[1])
    if len(sys.argv) > 2:
        month = int(sys.argv[2])
    
    try:
        result = generate_monthly_backup(year, month)
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error generating backup: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

