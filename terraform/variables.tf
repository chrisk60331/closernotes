variable "aws_region" {
  type        = string
  description = "AWS region for deployment."
  default     = "us-west-2"
}

variable "app_name" {
  type        = string
  description = "Base name for App Runner and related resources."
  default     = "closernotes"
}

variable "environment" {
  type        = string
  description = "Deployment environment (dev, staging, prod)."
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of dev, staging, prod."
  }
}

variable "container_port" {
  type        = number
  description = "Container port exposed by the service."
  default     = 5000
}

variable "flask_debug" {
  type        = bool
  description = "Enable Flask debug mode."
  default     = false
}

variable "ecr_image_tag" {
  type        = string
  description = "Base image tag for ECR images."
  default     = "latest"
}

variable "cpu" {
  type        = number
  description = "CPU units for App Runner."
  validation {
    condition     = contains([256, 512, 1024, 2048, 4096], var.cpu)
    error_message = "cpu must be one of 256, 512, 1024, 2048, 4096."
  }
}

variable "memory" {
  type        = number
  description = "Memory (MB) for App Runner."
  validation {
    condition     = var.memory >= 512 && var.memory <= 12288
    error_message = "memory must be between 512 and 12288 MB."
  }
}

variable "min_instances" {
  type        = number
  description = "Minimum App Runner instances."
  default     = 1
}

variable "max_instances" {
  type        = number
  description = "Maximum App Runner instances."
  default     = 2
}

variable "max_concurrency" {
  type        = number
  description = "Maximum requests per instance."
  default     = 100
}

variable "health_check_path" {
  type        = string
  description = "Health check path."
  default     = "/health"
}

variable "health_check_interval" {
  type        = number
  description = "Health check interval in seconds."
  default     = 10
}

variable "health_check_timeout" {
  type        = number
  description = "Health check timeout in seconds."
  default     = 5
}

variable "health_check_healthy_threshold" {
  type        = number
  description = "Number of consecutive successes to mark healthy."
  default     = 1
}

variable "health_check_unhealthy_threshold" {
  type        = number
  description = "Number of consecutive failures to mark unhealthy."
  default     = 5
}

variable "ecr_retain_count" {
  type        = number
  description = "Number of tagged images to retain per environment."
  default     = 10
}

variable "ecr_untagged_expire_days" {
  type        = number
  description = "Days before untagged images expire."
  default     = 7
}

variable "backboard_api_key" {
  type        = string
  description = "Backboard API key."
  sensitive   = true
}

variable "orchestrator_assistant_id" {
  type        = string
  description = "Orchestrator assistant ID in Backboard. Leave empty for auto-creation at runtime."
  sensitive   = true
  default     = ""
}

variable "users_assistant_id" {
  type        = string
  description = "Users assistant ID in Backboard. Leave empty for auto-creation at runtime."
  sensitive   = true
  default     = ""
}

variable "cache_assistant_id" {
  type        = string
  description = "Cache assistant ID in Backboard. Leave empty for auto-creation at runtime."
  sensitive   = true
  default     = ""
}
