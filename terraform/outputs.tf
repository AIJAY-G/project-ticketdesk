# ==============================================================================
# Outputs: Networking
# ==============================================================================
output "vpc_id" {
  description = "The ID of the TicketDesk VPC."
  value       = aws_vpc.main.id
}

output "public_subnet_id" {
  description = "The ID of the public subnet for EC2."
  value       = aws_subnet.public.id
}

output "private_subnet_ids" {
  description = "The IDs of the private subnets for RDS."
  value       = aws_subnet.private[*].id
}

output "ec2_security_group_id" {
  description = "The ID of the EC2 security group."
  value       = aws_security_group.ec2.id
}

output "rds_security_group_id" {
  description = "The ID of the RDS security group."
  value       = aws_security_group.rds.id
}

# ==============================================================================
# Outputs: S3 Storage & IAM
# ==============================================================================
output "s3_bucket_name" {
  description = "The name of the S3 bucket created for ticket attachments."
  value       = aws_s3_bucket.attachments.id
}

output "s3_bucket_arn" {
  description = "The ARN of the S3 bucket created for ticket attachments."
  value       = aws_s3_bucket.attachments.arn
}

output "ec2_iam_instance_profile_name" {
  description = "The name of the IAM instance profile for the EC2 application host."
  value       = aws_iam_instance_profile.ec2.name
}

# ==============================================================================
# Outputs: Database (Amazon RDS PostgreSQL)
# ==============================================================================
output "rds_endpoint" {
  description = "The connection endpoint (hostname:port) for the PostgreSQL database."
  value       = aws_db_instance.postgres.endpoint
}

output "rds_address" {
  description = "The private DNS hostname of the PostgreSQL database instance."
  value       = aws_db_instance.postgres.address
}

output "rds_port" {
  description = "The port on which the PostgreSQL database accepts connections."
  value       = aws_db_instance.postgres.port
}

output "rds_database_name" {
  description = "The name of the default database created on RDS."
  value       = aws_db_instance.postgres.db_name
}

output "rds_username" {
  description = "The master username for connecting to the PostgreSQL database."
  value       = aws_db_instance.postgres.username
}

# ==============================================================================
# Outputs: Compute (Amazon EC2 Application Server)
# ==============================================================================
output "ec2_instance_id" {
  description = "The ID of the EC2 application server instance."
  value       = aws_instance.app_server.id
}

output "ec2_public_ip" {
  description = "The public IPv4 address assigned to the EC2 application server."
  value       = aws_instance.app_server.public_ip
}

output "ec2_public_dns" {
  description = "The public DNS name assigned to the EC2 application server."
  value       = aws_instance.app_server.public_dns
}

output "ec2_private_ip" {
  description = "The private IPv4 address assigned to the EC2 application server."
  value       = aws_instance.app_server.private_ip
}


