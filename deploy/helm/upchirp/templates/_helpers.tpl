{{- define "upchirp.labels" -}}
app.kubernetes.io/part-of: upchirp
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Database password: generated once, then kept across upgrades. */}}
{{- define "upchirp.dbPassword" -}}
{{- $existing := lookup "v1" "Secret" .Release.Namespace "upchirp-db" -}}
{{- if $existing -}}
{{- index $existing.data "password" | b64dec -}}
{{- else -}}
{{- randAlphaNum 24 -}}
{{- end -}}
{{- end }}

{{- define "upchirp.appEnv" -}}
- name: UPCHIRP_KAFKA
  value: redpanda:9092
- name: DB_PASSWORD
  valueFrom: {secretKeyRef: {name: upchirp-db, key: password}}
- name: UPCHIRP_DATABASE_URL
  value: postgresql://upchirp:$(DB_PASSWORD)@db:5432/upchirp
- name: UPCHIRP_DATA_DIR
  value: /data
- name: OLLAMA_HOST
  value: http://ollama:11434
- name: UPCHIRP_MODEL
  value: ollama
- name: UPCHIRP_OLLAMA_MODEL
  value: {{ .Values.agent.model | quote }}
- name: UPCHIRP_PUBLIC
  value: {{ if .Values.agent.public }}"1"{{ else }}"0"{{ end }}
{{- end }}
