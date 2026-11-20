# ==============================================================================
# Amazon RDS DB Subnet Group
# Must span at least two Availability Zones in the chosen region.
# Uses the private subnets created in vpc.tf.
# ==============================================================================
resource "aws_db_subnet_group" "main" {
  name        = "${var.project_name}-${var.environment}-db-subnet-group"
  description = "Database subnet group for TicketDesk private PostgreSQL instance"
  subnet_ids  = aws_subnet.private[*].id

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-subnet-group"
    Environment = var.environment
  }
}

# ==============================================================================
# Amazon RDS PostgreSQL Database Instance
# ==============================================================================
resource "aws_db_instance" "postgres" {
  identifier = "${var.project_name}-${var.environment}-db"

  # Engine & Version
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  # Storage configuration (gp3 SSD, cost-optimized for PoC)
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = 0 # Disables storage autoscaling for PoC to prevent unexpected costs
  storage_type          = "gp3"

  # Database Name & Credentials
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password
  port     = var.db_port

  # Networking & Virtual Firewall
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false # Strictly private, no public IP, no internet routing

  # Availability & Durability (Cost-minimized for internship PoC)
  multi_az            = false # Single-AZ to avoid doubling hourly database cost
  skip_final_snapshot = true  # Enables clean teardown with terraform destroy
  deletion_protection = false # Allows clean teardown for internship PoC

  # Maintenance & Automated Backups
  auto_minor_version_upgrade = true
  backup_retention_period    = 1

  tags = {
    Name        = "${var.project_name}-${var.environment}-postgres"
    Purpose     = "TicketDesk Operational Database"
    Environment = var.environment
  }
}
