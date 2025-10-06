# ☕ Laurin Build - Coffee Management System

A beautiful, coffee-themed beverage management system for the Christian School in Hegau (CSH).

## 🎨 Features

- **Coffee Theme**: Warm, cozy coffee-inspired design throughout
- **Dual Interface**: Separate Admin and User views
- **Guest Access**: Special guest role for visitors
- **Monthly Reports**: Comprehensive consumption analytics
- **Security**: Admin backdoor with security gate
- **Responsive**: Works on desktop, tablet, and mobile

## 🚀 Quick Start

### Laptop Development
```bash
# Start the system
./start_laptop.sh

# Stop the system
./stop_laptop.sh
```

### Access Points
- **Admin Interface**: http://localhost:5001
- **User Interface**: http://localhost:5002
- **Database Admin**: http://localhost:8080

## 🏗️ Architecture

### Docker Services
- **Admin Container**: `laurin_build_admin` (Port 5001)
- **User Container**: `laurin_build_user` (Port 5002)
- **Database**: `laurin_build_db` (PostgreSQL)
- **Adminer**: `laurin_build_adminer` (Port 8080)
- **Redis**: `laurin_build_redis` (Caching)

### Key Files
- `docker-compose.laptop.yml` - Development environment
- `Dockerfile.laptop` - Optimized for laptop development
- `app/` - Main application code
- `app/static/css/` - Coffee-themed stylesheets
- `app/templates/` - HTML templates

## 🎯 Admin Features

- **User Management**: Add, edit, and manage users
- **Beverage Management**: Configure drinks and prices
- **Monthly Reports**: Detailed consumption analytics
- **Security Gate**: Protected admin access
- **Admin Backdoor**: Direct user access for support

## 👥 User Features

- **Beverage Selection**: Choose from available drinks
- **PIN System**: Secure user identification
- **Guest Access**: Special role for visitors
- **Consumption Tracking**: View personal consumption
- **Coffee Theme**: Beautiful, cozy interface

## 🔧 Development

### Environment Variables
- `FLASK_APP_MODE`: `admin` or `user`
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: Application secret key

### Database
- **Type**: PostgreSQL
- **Backup**: Automatic UTF-8 conversion
- **Encoding**: Full German umlaut support (ö, ä, ü, ß)

## 📱 Deployment

### Server Deployment
1. Copy files to server
2. Run `./deploy_to_server.sh`
3. Import database backup
4. Access via server IP

### GitHub Integration
- Repository: `laurin-build`
- Authentication: Personal Access Token
- Branch: `main`

## 🎨 Design System

### Color Palette
- **Primary**: Coffee Brown (#8B4513)
- **Secondary**: Orange (#D2691E)
- **Accent**: Burlywood (#CD853F)
- **Background**: Cream gradients
- **Text**: Coffee brown tones

### Typography
- **Font**: Segoe UI, Tahoma, Geneva, Verdana
- **Weights**: 400, 500, 600, 700, 800
- **Shadows**: Subtle coffee-themed shadows

## 🔒 Security

- **Admin Token**: Secure token (generated from admin secret key)
- **Security Gate**: Access code protection
- **PIN System**: User identification
- **Guest Role**: Limited access for visitors

## 📊 Reports

- **Monthly Analytics**: User consumption patterns
- **Revenue Tracking**: Financial summaries
- **Export Options**: CSV and print formats
- **Visual Charts**: Coffee-themed data presentation

## 🛠️ Maintenance

### Database Issues
- Run `./fix_all_issues.sh` for character encoding fixes
- Use `./import_complete_data.sh` for clean data import

### Development
- Use `./start_laptop.sh` for local development
- Access Adminer for database management
- Check logs in Docker containers

## 📞 Support

For technical support or questions about the Laurin Build system, refer to the documentation files:
- `README_LAPTOP.md` - Development setup
- `SECURITY_GUIDE.md` - Security features
- `DEPLOYMENT.md` - Server deployment
- `GITHUB_SETUP_LAURIN.md` - GitHub integration

---

**Built with ☕ and ❤️ for CSH**
