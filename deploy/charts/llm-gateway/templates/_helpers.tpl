{{- define "llm-gateway.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "llm-gateway.labels" -}}
app.kubernetes.io/name: {{ include "llm-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "llm-gateway.selector" -}}
app.kubernetes.io/name: {{ include "llm-gateway.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "llm-gateway.image" -}}
{{- if .Values.image.digest -}}
{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}
{{ .Values.image.repository }}:{{ required "image.digest or image.tag is required" .Values.image.tag }}
{{- end -}}
{{- end -}}

{{/* Environment shared by the API and the worker. */}}
{{- define "llm-gateway.env" -}}
- name: LLMGW_ENVIRONMENT
  value: {{ .Values.environment | quote }}
- name: LLMGW_AWS_REGION
  value: {{ .Values.region | quote }}
- name: AWS_REGION
  value: {{ .Values.region | quote }}
- name: LLMGW_LOG_LEVEL
  value: {{ .Values.logLevel | quote }}
- name: LLMGW_ROUTING_CONFIG_PATH
  value: /etc/llm-gateway/routing.yaml
- name: LLMGW_TENANT_HEADER
  value: {{ .Values.tenantHeader | quote }}
- name: LLMGW_VALKEY_URL
  value: {{ printf "rediss://%s/0" (required "valkey.endpoint is required" .Values.valkey.endpoint) | quote }}
- name: LLMGW_VALKEY_CLUSTER_MODE
  value: {{ .Values.valkey.clusterMode | quote }}
- name: LLMGW_VALKEY_TIMEOUT_S
  value: {{ .Values.valkey.timeoutSeconds | quote }}
- name: LLMGW_VALKEY_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.valkey.authSecretName }}
      key: password
- name: LLMGW_REGION_QUOTA_SHARE
  value: {{ .Values.regionQuotaShare | quote }}
- name: LLMGW_LOCAL_FALLBACK_FRACTION
  value: {{ .Values.localFallbackFraction | quote }}
- name: LLMGW_TENANTS_TABLE
  value: {{ .Values.dynamodb.tenantsTable | quote }}
- name: LLMGW_USAGE_TABLE
  value: {{ .Values.dynamodb.usageTable | quote }}
{{- if .Values.jobsQueueUrl }}
- name: LLMGW_JOBS_TABLE
  value: {{ .Values.dynamodb.jobsTable | quote }}
- name: LLMGW_JOBS_QUEUE_URL
  value: {{ .Values.jobsQueueUrl | quote }}
{{- end }}
- name: LLMGW_OTEL_ENABLED
  value: {{ .Values.otel.enabled | quote }}
{{- if .Values.otel.enabled }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.otel.endpoint | quote }}
{{- end }}
{{- end -}}

{{/* Pod-level settings shared by the API and the worker. */}}
{{- define "llm-gateway.podAnnotations" -}}
checksum/routing: {{ toYaml .Values.routing | sha256sum }}
# EKS Pod Identity credentials come from this link-local agent; keep it outside the
# mesh, which only allows registered destinations.
traffic.sidecar.istio.io/excludeOutboundIPRanges: 169.254.170.23/32
{{- end -}}
