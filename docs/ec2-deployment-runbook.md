# TicketDesk POC — EC2 Application Deployment Runbook

> **Target Audience**: Infrastructure Leads, DevOps Engineers, and Cloud Operations Administrators  
> **Target OS**: Amazon Linux 2023 (x86_64)  
> **Compute Instance**: Amazon EC2 `t3.micro`  
> **AWS Region**: `ap-south-1` (Asia Pacific - Mumbai)  
> **Repository**: [AIJAY-G/project-ticketdesk](https://github.com/AIJAY-G/project-ticketdesk.git)  

---

## 1. Architecture Overview

```
                      [ Public Internet ]
                               │
                               │ HTTP (Port 80)
                               ▼
        ┌─────────────────────────────────────────────────┐
        │  Amazon EC2 Application Server (AL2023)         │
        │                                                 │
        │   ┌─────────────────────────────────────────┐   │
        │   │ Nginx Reverse Proxy (Port 80)           │   │
        │   └────────────────────┬────────────────────┘   │
        │                        │ (127.0.0.1:8000)       │
        │                        ▼                        │
        │   ┌─────────────────────────────────────────┐   │
        │   │ systemd: ticketdesk.service             │   │
        │   │ (Uvicorn / FastAPI, non-root user)      │   │
        │   └───────────────┬─────────────────┬───────┘   │
        └───────────────────┼─────────────────┼───────────┘
                            │                 │
             PostgreSQL 5432│                 │ PutObject / GetObject
             (Encrypted SSL)│                 │ (IAM Instance Profile)
                            ▼                 ▼
          ┌───────────────────────┐   ┌───────────────────────┐
          │ Amazon RDS PostgreSQL │   │ Amazon S3 Bucket      │
          │ (Strictly Private)    │   │ (Encrypted, Private)  │
          └───────────────────────┘   └───────────┬───────────┘
                                                  │
                                                  │ s3:ObjectCreated:*
                                                  ▼
                                      ┌───────────────────────┐
                                      │ AWS Lambda Processor  │
                                      │ (Outside VPC, $0)     │
                                      └───────────────────────┘
```

### Security & Isolation Principles
- **No Direct Port 8000 Public Ingress**: Uvicorn binds strictly to `127.0.0.1:8000`. Only Nginx accepts inbound traffic on public port 80.
- **Zero Static AWS Credentials**: The EC2 application server assumes an IAM Role (`aws_iam_instance_profile.ec2`) to interact with S3. No AWS access keys are stored on disk.
- **No Open SSH Port**: Administrative access is performed exclusively through **AWS Systems Manager (SSM) Session Manager**, avoiding port 22 exposure and SSH key management.
- **Dedicated Non-Root User**: Application executes under user `ticketdesk` with limited filesystem privileges and systemd sandboxing (`ProtectSystem=full`, `PrivateTmp=true`, `NoNewPrivileges=true`).

---

## 2. Pre-Deployment Readiness Checklist

Before beginning deployment, ensure the following parameters are collected from the Terraform deployment step:

- [ ] Terraform infrastructure applied in `ap-south-1`.
- [ ] Captured `ec2_instance_id` (e.g., `i-0123456789abcdef0`).
- [ ] Captured `ec2_public_ip` (e.g., `13.235.x.x`).
- [ ] Captured `rds_address` (e.g., `ticketdesk-poc-db.xxxx.ap-south-1.rds.amazonaws.com`).
- [ ] Captured `s3_bucket_name` (e.g., `ticketdesk-poc-attachments-xxxx`).
- [ ] Database master password that was configured in `terraform.tfvars`.
- [ ] AWS CLI configured locally with permissions for `ssm:StartSession`.

---

## 3. Step-by-Step EC2 Application Deployment Walkthrough

### Step 1: Connect to the EC2 Host via AWS SSM Session Manager
Open your local terminal and connect to the EC2 host without SSH keys:

```bash
aws ssm start-session --target <ec2_instance_id> --region ap-south-1
```

Once connected, switch to root to perform initial system configuration:
```bash
sudo su -
```

### Step 2: Clone the Project Repository to a Staging Directory
Clone the repository to a temporary workspace on the EC2 host:

```bash
cd /tmp
git clone https://github.com/AIJAY-G/project-ticketdesk.git
cd project-ticketdesk
```

*(Optional: checkout a specific release tag or integration branch if needed)*:
```bash
git checkout main
```

### Step 3: Run the Automated Installation Script
Execute the deployment script:

```bash
bash deploy/install.sh
```

**What the script performs automatically**:
1. Installs Python 3.11, pip, git, and Nginx via Amazon Linux `dnf`.
2. Creates the non-root system user `ticketdesk`.
3. Creates the `/opt/ticketdesk` directory hierarchy.
4. Copies application code to `/opt/ticketdesk/app/`.
5. Creates a Python 3.11 virtual environment at `/opt/ticketdesk/venv`.
6. Installs Python dependencies (`fastapi`, `uvicorn`, `psycopg2-binary`, `boto3`, etc.).
7. Installs systemd service `/etc/systemd/system/ticketdesk.service`.
8. Configures Nginx reverse proxy at `/etc/nginx/conf.d/ticketdesk.conf`.
9. Sets directory ownership to `ticketdesk:ticketdesk` and file permissions to `750`.
10. Enables and starts `ticketdesk.service` and `nginx`.

### Step 4: Configure Production Environment Variables
Edit the application `.env` file created at `/opt/ticketdesk/app/.env`:

```bash
nano /opt/ticketdesk/app/.env
```

Set the actual cloud values:

```ini
# Database Connection (Amazon RDS PostgreSQL)
DATABASE_URL=postgresql+psycopg2://ticketdesk_admin:<YOUR_DB_PASSWORD>@<YOUR_RDS_ADDRESS>:5432/ticketdesk?sslmode=require

# Attachment Storage (Amazon S3)
S3_BUCKET_NAME=<YOUR_S3_BUCKET_NAME>
AWS_REGION=ap-south-1

# JWT Token Signing Secret (Generate with: python3 -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET_KEY=<YOUR_GENERATED_64_CHAR_HEX_SECRET>
SECRET_KEY=<YOUR_GENERATED_64_CHAR_HEX_SECRET>
TOKEN_EXPIRATION_SECONDS=86400

# Strict Production Authentication (Disable dev header auth)
ALLOW_DEV_HEADER_AUTH=False

# Admin Account Configuration
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<STRONG_ADMIN_PASSWORD>
SEED_DEMO_ACCOUNTS=False
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

Ensure secure file permissions on the `.env` file:
```bash
chmod 600 /opt/ticketdesk/app/.env
chown ticketdesk:ticketdesk /opt/ticketdesk/app/.env
```

### Step 5: Restart the TicketDesk Application Service
Restart the service to load the newly configured environment:

```bash
systemctl restart ticketdesk.service
```

Verify service status:
```bash
systemctl status ticketdesk.service
```

Expected output: `Active: active (running)`.

---

## 4. Verification and Health Checks

### Check 1: Local Internal Health Check (Uvicorn Port 8000)
From within the EC2 instance, test Uvicorn directly:
```bash
curl -i http://127.0.0.1:8000/health
```
**Expected Output**:
```http
HTTP/1.1 200 OK
content-type: application/json

{"status":"healthy","service":"ticketdesk"}
```

### Check 2: Reverse Proxy Health Check (Nginx Port 80)
From within the EC2 instance, test Nginx routing:
```bash
curl -i http://127.0.0.1/health
```
**Expected Output**:
```http
HTTP/1.1 200 OK
server: nginx
content-type: application/json

{"status":"healthy","service":"ticketdesk"}
```

### Check 3: External Browser Verification
Open your browser and navigate to:
```
http://<ec2_public_ip>/
```
- The TicketDesk single-page application UI loads.
- Log in using `admin` and your configured `ADMIN_PASSWORD`.
- Create a test ticket and upload a supported attachment (`.png`, `.pdf`, `.log`).
- Confirm attachment upload succeeds and download link functions.

### Check 4: Lambda Serverless Event Verification
Verify the attachment triggered the Lambda processor:
1. Open AWS Management Console > CloudWatch > Log groups.
2. Select `/aws/lambda/ticketdesk-poc-attachment-processor`.
3. Open the latest log stream and confirm the structured JSON log entry:
   `"event_type": "ATTACHMENT_PROCESSED_SUCCESSFULLY"`.

---

## 5. Troubleshooting Guide

### Issue 1: Nginx Returns "502 Bad Gateway"
- **Cause**: Uvicorn is not running or failed to bind to `127.0.0.1:8000`.
- **Diagnosis**:
  ```bash
  sudo journalctl -u ticketdesk -n 50 --no-pager
  ```
- **Remediation**: Look for Python traceback. Check if a dependency is missing or if `.env` has invalid syntax.

### Issue 2: Application Fails with "FATAL: password authentication failed" or "connection refused"
- **Cause**: Invalid `DATABASE_URL` or database is still initializing.
- **Diagnosis**:
  ```bash
  sudo journalctl -u ticketdesk | grep -i "database"
  ```
- **Remediation**:
  1. Verify `DATABASE_URL` in `/opt/ticketdesk/app/.env`. Ensure `sslmode=require` is appended.
  2. Confirm RDS security group allows ingress on port 5432 from `aws_security_group.ec2.id`.
  3. Ensure RDS instance state is `Available` in AWS console.

### Issue 3: S3 Upload Error: "Access Denied" or "ClientError"
- **Cause**: EC2 instance profile missing S3 permissions or bucket name mismatch.
- **Diagnosis**:
  ```bash
  sudo journalctl -u ticketdesk | grep -i "s3"
  ```
- **Remediation**:
  1. Check `S3_BUCKET_NAME` in `/opt/ticketdesk/app/.env`.
  2. Confirm EC2 has IAM Instance Profile `ticketdesk-poc-ec2-instance-profile` attached in AWS console.

### Issue 4: Nginx Returns "413 Request Entity Too Large"
- **Cause**: Uploaded file exceeds Nginx `client_max_body_size`.
- **Remediation**: Verify `/etc/nginx/conf.d/ticketdesk.conf` includes `client_max_body_size 15M;` and run `sudo nginx -s reload`.

---

## 6. Rollback Procedure

If a deployment update fails or instability is observed, execute the automated rollback script:

```bash
sudo bash /opt/ticketdesk/deploy/rollback.sh
```

**What the rollback script performs**:
1. Identifies the most recent backup snapshot (`/opt/ticketdesk.bak.<timestamp>`).
2. Stops `ticketdesk.service`.
3. Safely preserves the existing production `/opt/ticketdesk/app/.env`.
4. Restores application files from the backup.
5. Re-applies ownership and permissions.
6. Restarts `ticketdesk.service` and `nginx`.
7. Displays active service status.
