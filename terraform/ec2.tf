# ==============================================================================
# Amazon Linux 2023 AMI Dynamic Lookup
# ==============================================================================
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
}

# ==============================================================================
# TicketDesk EC2 Application Server Instance
# ==============================================================================
resource "aws_instance" "app_server" {
  ami           = data.aws_ami.amazon_linux_2023.id
  instance_type = var.ec2_instance_type

  # Networking: Placed in the Public Subnet created in vpc.tf
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  associate_public_ip_address = true

  # IAM Instance Profile: Attached for S3 access & CloudWatch logging (iam.tf)
  iam_instance_profile = aws_iam_instance_profile.ec2.name

  # Optional SSH Key Pair (null by default; SSM Session Manager preferred)
  key_name = var.ec2_key_name

  # Storage configuration: 20 GB gp3 encrypted root volume (Free Tier eligible)
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.ec2_root_volume_size
    delete_on_termination = true
    encrypted             = true
  }

  # Minimal, safe bootstrap script (prepares Python 3.11 runtime; contains zero secrets)
  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3.11 python3.11-pip git
              EOF

  tags = {
    Name        = "${var.project_name}-${var.environment}-app-server"
    Purpose     = "TicketDesk FastAPI Application Server"
    Environment = var.environment
  }
}

