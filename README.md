# 🌍 AfriData – African Dataset Hub

**AfriData** is a comprehensive, Django-based open-data repository designed to serve as a centralized hub for datasets across the African continent. Created and managed by **JHUB Africa**, AfriData facilitates seamless discovery, upload, download, and programmatic integration of public data across education, health, agriculture, economics, and regional development domains.

---

## 📌 Project Overview

AfriData is designed with modern Full-Stack and DevOps practices. It provides:
1. **Dataset Discovery & Curation**: Clean, filterable catalogs with dynamic search and categorization.
2. **Community Forum**: An engaging discussion and request space for developers and researchers.
3. **RESTful API**: Standardized programmatic endpoints secured using session & token authentication.
4. **Developer-Friendly Architecture**: Standardized template comments, optimized frontend structures, and seamless containerization.

---

## 🧱 Repository Structure

A quick guide to finding files and services in the codebase:

```bash
afridata_1/
├── afridata/          # Core Django project configuration settings & URLs
├── accounts/          # User authentication models, profile services, and views
├── dataset/           # Dataset model logic, catalog listing, and storage utilities
├── community/         # Forum discussion boards, categories, and user messaging
├── api/               # Django REST Framework viewsets and serializer schemas
├── mpesa/             # Integration logic for mobile-money payments (Lipa Na M-Pesa)
├── templates/         # Clean HTML templates (split into page components)
│   ├── base.html      # Global site wrapper, containing Tailwind configuration
│   └── components/    # Reusable fragments (navbar, footer, toast notices)
├── Dockerfile         # Python-slim deployment recipe
├── docker-compose.yml # Dual-service configuration (Web App + MySQL 5.7 DB)
└── entrypoint.sh      # DB-ready checking, migrations, and Gunicorn runtime execution
```

---

## ⚙️ Core Prerequisites

Ensure the following environments are installed on your host system:
* **Python**: `3.11`
* **Database**: `SQLite` (for fast local development) or `MySQL 5.7` / `MariaDB` (production/Docker)
* **Docker & Compose** *(Optional)*: Recommended for production-parity local testing

---

## 🚀 Getting Started

Select one of the two setup paths below to run the application:

### Option A: Local Development Setup (Manual)

#### 1. Clone & Navigate to Project
```bash
git clone <repository-url>
cd afridata_1
```

#### 2. Create & Activate Virtual Environment
```bash
# On Linux/macOS
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```

#### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. Configure Environment Variables
Copy the template configuration file:
```bash
cp .env.example .env
```
Open `.env` and configure key variables:
* Set `GEMINI_API_KEY` for LLM capabilities.
* Review the **Email / SMTP Configuration** section below to configure emails.

#### 5. Initialize the Database
Make and apply database migrations, then load standard super administrators:
```bash
python manage.py makemigrations
python manage.py migrate
python setup_admins.py
```

#### 6. Run the Server
```bash
python manage.py runserver
```
Visit the local site at: **`http://127.0.0.1:8000/`**

---

### Option B: Docker Containerized Setup (DevOps Standard)

The repository comes packaged with a pre-configured multi-container Docker structure that initiates a MySQL 5.7 database container alongside the Gunicorn-served Django web application.

#### 1. Copy Environment File
```bash
cp .env.example .env
```

#### 2. Spin Up Containers
```bash
docker-compose up --build
```

#### 3. Under the Hood (Initialization Sequence)
When you run `docker-compose up`, the `entrypoint.sh` automatically performs:
1. Verification of database socket availability (netcat loop).
2. Auto-generation of new database schemas (`makemigrations`).
3. Application of database migrations (`migrate`).
4. Collection of static files (`collectstatic`).
5. Seeding of the default Admin accounts (`setup_admins.py`).
6. Launch of the production-ready **Gunicorn** server on port `8000`.

---

## 📧 Email & SMTP Configuration

To prevent onboarding friction, AfriData handles emails differently depending on the `DEBUG` environment state:

### 1. Development Mode (`DEBUG=True`)
* **No SMTP credentials required!**
* Emails (such as password resets, token confirmations, and contact submissions) are routed to Django's **Console Backend**. 
* Instead of being sent out to a real inbox, they will be **printed directly to your terminal standard output (stdout)**. Look at your running `runserver` window to find verification links.

### 2. Production Mode (`DEBUG=False`)
* The system utilizes Gmail's SMTP servers by default to send real emails to users.
* To configure this, add the following variables to your `.env` file:
  ```env
  EMAIL_HOST_USER=your-organization-email@gmail.com
  EMAIL_HOST_PASSWORD=your-google-app-password
  CONTACT_EMAIL_RECIPIENT=info.jhub@jkuat.ac.ke
  ```

#### 🔒 How to generate a Google App Password:
1. Go to your **Google Account settings** (security section).
2. Enable **2-Step Verification** (required by Google to use App Passwords).
3. Search for **App Passwords** in the search bar or go directly to the page.
4. Create a new App Password, select **Other (Custom name)**, and name it `AfriData`.
5. Copy the generated **16-character code** (without spaces) and paste it into the `EMAIL_HOST_PASSWORD` field in your `.env`.

---

## 🛡️ Default Administrator Accounts

Once your migrations have run and `setup_admins.py` executes, the following users are pre-configured:

| Username | Email | Initial Password | Role / Details |
| :--- | :--- | :--- | :--- |
| `info.jhub` | `info.jhub@jkuat.ac.ke` | `JHubAdminPassword2026!` | JHub Admin Account |
| `jaksoftwares05` | `jaksoftwares05@gmail.com` | `JakAdminPassword2026!` | System DevOps Account |

---

## 🌐 API Overview

AfriData provides a built-in RESTful API accessible at `/api/`:

| HTTP Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| **GET** | `/api/datasets/` | Lists all datasets (paginated) | No |
| **GET** | `/api/datasets/<id>/` | Retrieves single dataset metadata | No |
| **POST** | `/api/datasets/` | Uploads a new dataset | Yes (Token/Session) |
| **POST** | `/api/token/` | Generates a JWT token for API users | No |
| **GET** | `/api/categories/` | Lists available dataset categories | No |

---

## 🛠️ Environment Configuration Reference

| Key Name | Default Value | Description |
| :--- | :--- | :--- |
| `DEBUG` | `True` | Set to `False` in production to switch to MySQL and real SMTP backends. |
| `SECRET_KEY` | *auto-generated* | Encryption secret for sessions/salts. |
| `LLM_BACKEND` | `gemini` | Language model provider (`gemini` / `openai` / `anthropic` / `ollama`). |
| `GEMINI_API_KEY` | *None* | Google Generative AI API Token. |
| `DATABASE_URL` | *None* | Connection URL for MySQL (used automatically by Docker). |
| `MPESA_CALLBACK_URL`| *None* | Callback listener URL (must be HTTPS in production). |
| `EMAIL_HOST_USER` | *None* | Sender email address for SMTP mailing. |
| `EMAIL_HOST_PASSWORD`| *None* | Google App Password or SMTP key. |
| `CONTACT_EMAIL_RECIPIENT`| `info.jhub@jkuat.ac.ke` | Recipient address for the contact form. |

---

## 💡 Troubleshooting & FAQs

* **Database Connection Failing (Docker)**:
  Ensure port `3306` is not already occupied on your host system by another running database. If it is, edit `docker-compose.yml` to remap host port: `"3307:3306"`.
* **Missing CSS/JS in Production mode (`DEBUG=False`)**:
  Run `python manage.py collectstatic --noinput` to consolidate styling assets into the unified static root.
* **SMTP Reset Mails Failing**:
  Verify `DEBUG=False` is set in production. Double check that `EMAIL_HOST_USER` matches the account that generated the `EMAIL_HOST_PASSWORD` (App Password).

---

## 📄 License
This project is licensed under the **MIT License**. See the `LICENSE` file for more information.

---

## ✉️ Maintainer & Organization
* **Owner/Publisher**: JHUB Africa
* **Location**: Nairobi, Kenya
* **Support Contact**: info@afridata.jhubafrica.com
