data "aws_iam_policy_document" "apprunner_ecr_access_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_ecr_access" {
  name               = "${local.service_name}-ecr-access"
  assume_role_policy = data.aws_iam_policy_document.apprunner_ecr_access_assume_role.json
}

resource "aws_iam_role_policy_attachment" "apprunner_ecr_access" {
  role       = aws_iam_role.apprunner_ecr_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

data "aws_iam_policy_document" "apprunner_instance_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${local.service_name}-instance"
  assume_role_policy = data.aws_iam_policy_document.apprunner_instance_assume_role.json
}

resource "aws_ssm_parameter" "backboard_api_key" {
  name        = "/${var.app_name}/${var.environment}/backboard-api-key"
  description = "Backboard API key for ${local.service_name}"
  type        = "SecureString"
  value       = var.backboard_api_key
}

resource "aws_ssm_parameter" "orchestrator_assistant_id" {
  name        = "/${var.app_name}/${var.environment}/orchestrator-assistant-id"
  description = "Orchestrator assistant ID for ${local.service_name}"
  type        = "SecureString"
  value       = var.orchestrator_assistant_id
}

resource "aws_ssm_parameter" "users_assistant_id" {
  name        = "/${var.app_name}/${var.environment}/users-assistant-id"
  description = "Users assistant ID for ${local.service_name}"
  type        = "SecureString"
  value       = var.users_assistant_id
}

resource "aws_ssm_parameter" "cache_assistant_id" {
  name        = "/${var.app_name}/${var.environment}/cache-assistant-id"
  description = "Cache assistant ID for ${local.service_name}"
  type        = "SecureString"
  value       = var.cache_assistant_id
}

resource "aws_iam_role_policy" "apprunner_instance_ssm_access" {
  name = "${local.service_name}-ssm-access"
  role = aws_iam_role.apprunner_instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters"
        ]
        Resource = [
          aws_ssm_parameter.backboard_api_key.arn,
          aws_ssm_parameter.orchestrator_assistant_id.arn,
          aws_ssm_parameter.users_assistant_id.arn,
          aws_ssm_parameter.cache_assistant_id.arn,
        ]
      }
    ]
  })
}

resource "aws_apprunner_auto_scaling_configuration_version" "app" {
  auto_scaling_configuration_name = "${local.service_name}-scaling"
  min_size                        = var.min_instances
  max_size                        = var.max_instances
  max_concurrency                 = var.max_concurrency
}

resource "aws_apprunner_service" "app" {
  service_name = local.service_name

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.app.arn

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }

    image_repository {
      image_identifier      = "${aws_ecr_repository.app.repository_url}:${var.environment}-${var.ecr_image_tag}"
      image_repository_type = "ECR"

      image_configuration {
        port = tostring(var.container_port)
        runtime_environment_variables = {
          FLASK_HOST  = "0.0.0.0"
          FLASK_PORT  = tostring(var.container_port)
          FLASK_DEBUG = tostring(var.flask_debug)
          ENVIRONMENT = var.environment
        }
        runtime_environment_secrets = {
          BACKBOARD_API_KEY        = aws_ssm_parameter.backboard_api_key.arn
          ORCHESTRATOR_ASSISTANT_ID = aws_ssm_parameter.orchestrator_assistant_id.arn
          USERS_ASSISTANT_ID       = aws_ssm_parameter.users_assistant_id.arn
          CACHE_ASSISTANT_ID       = aws_ssm_parameter.cache_assistant_id.arn
        }
      }
    }

    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = tostring(var.cpu)
    memory            = tostring(var.memory)
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = var.health_check_path
    interval            = var.health_check_interval
    timeout             = var.health_check_timeout
    healthy_threshold   = var.health_check_healthy_threshold
    unhealthy_threshold = var.health_check_unhealthy_threshold
  }
}
