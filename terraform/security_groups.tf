# ==============================================================================
# EC2 Application Server Security Group
# ==============================================================================
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-${var.environment}-ec2-sg"
  description = "Security group for TicketDesk EC2 application server"
  vpc_id      = aws_vpc.main.id

  # Inbound HTTP (port 80) for web traffic
  ingress {
    description = "Allow inbound HTTP web traffic"
    from_port   = var.http_port
    to_port     = var.http_port
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Inbound Application Port (port 8000) for FastAPI direct access
  dynamic "ingress" {
    for_each = var.app_port != var.http_port ? [var.app_port] : []
    content {
      description = "Allow inbound FastAPI application traffic"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  # Inbound SSH (port 22) strictly restricted to configured trusted CIDR
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

  # Outbound traffic (Permits package updates, S3 communication, and RDS access)
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

