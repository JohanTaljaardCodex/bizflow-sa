BIZFLOW DARK + PURPLE UI UPGRADE
================================

This package changes the LOOK ONLY.

REPLACE:
templates/public_base.html
templates/home.html
templates/growth_system.html
templates/how_it_works.html
templates/pricing.html
templates/contact.html
templates/operator_login.html
templates/base.html
templates/dashboard.html
static/style.css

BACKEND:
No database changes required.
No route changes required.
No Render environment variable changes required.

DEPLOY:
git add .
git commit -m "Add new BizFlow dark purple UI"
git push

RENDER:
Render should redeploy automatically.

CHECK:
/
 /growth-system
 /pricing
 /how-it-works
 /contact
 /operator/login
 /operator

The new logo is CSS-based, so there is no separate logo file to manage.
