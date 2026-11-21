# ==============================================================================
# EC2 Application Server Security Group
# ==============================================================================
# SECURITY POSTURE (Phase 10.2 - SSM-Only Private Access):
# 1. No Public Inbound HTTP/HTTPS: Public port 80 ingress (0.0.0.0/0) is removed.
#    Local browser access is established securely via AWS Systems Manager (SSM)
#    Session Manager port forwarding (localhost:8080 -> EC2 localhost:80).
# 2. Port 8000 Inaccessible from Internet: Uvicorn binds strictly to 127.0.0.1:8000
#    and has zero external security group ingress rules.
# 3. SSH Disabled by Default: Port 22 is disabled unless an explicit non-0.0.0.0/0
#    trusted CIDR is configured in 'allowed_ssh_cidr' (defaults to null).
# 4. Outbound Egress: Unrestricted (0.0.0.0/0) to enable package updates, S3
#    attachment management, RDS PostgreSQL connectivity, and outbound TLS
#    communication with regional AWS Systems Manager service endpoints.
# ==============================================================================
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-${var.environment}-ec2-sg"
  description = "Security group for TicketDesk EC2 application server (SSM-only access)"
  vpc_id      = aws_vpc.main.id

  # Inbound SSH (port 22) strictly restricted to configured trusted CIDR
  # Disabled by default when allowed_ssh_cidr is null (SSM Session Manager preferred)
  dynamic "ingress" {
    for_each = var.allowed_ssh_cidr != null && var.allowed_ssh_cidr != "" ? [var.allowed_ssh_cidr] : []
    content {
      description = "Allow SSH administration from trusted CIDR"
      from_port   = var.ssh_port
      to_port     = var.ssh_port
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  # Outbound traffic (Permits package updates, S3 communication, RDS access, and SSM endpoints)
  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ec2-sg"
  }
}

# ==============================================================================
# Amazon RDS PostgreSQL Security Group
# ==============================================================================
resource "aws_security_group" "rds" {
  name        = "${var.project_name}-${var.environment}-rds-sg"
  description = "Security group for TicketDesk Amazon RDS PostgreSQL database"
  vpc_id      = aws_vpc.main.id

  # Inbound PostgreSQL access strictly chained to EC2 Security Group
  # Never allows 0.0.0.0/0 or direct public ingress
  ingress {
    description     = "Allow PostgreSQL access strictly from EC2 application server"
    from_port       = var.db_port
    to_port         = var.db_port
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }

  # Outbound traffic restricted to internal VPC
  egress {
    description = "Allow outbound traffic within the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  }
}

