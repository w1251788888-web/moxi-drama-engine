import { v2Api } from '../http'

export interface LegalMaterialItem {
  material_type: string
  title: string
  provider: 'system' | 'user' | 'external' | string
  status: string
  detail: string
  file_path: string
  file_hash: string
}

export interface LegalMaterialMatrix {
  project_id: string
  rights_status: string
  rights_score: number
  system_generated: LegalMaterialItem[]
  user_required: LegalMaterialItem[]
  external_required: LegalMaterialItem[]
}

export interface RightsCheckResult {
  id: string
  project_id: string
  check_type: string
  status: 'pass' | 'warning' | 'blocked' | string
  score: number
  blockers: string[]
  warnings: string[]
  created_at: string
}

export interface EvidencePackage {
  id: string
  project_id: string
  package_type: string
  status: string
  package_path: string
  manifest_hash: string
  created_by: string
  created_at: string
}

export const legalAssetsApi = {
  getMatrix: (projectId: string) =>
    v2Api.get<LegalMaterialMatrix>(`/projects/${projectId}/legal-assets/matrix`),

  saveMaterial: (projectId: string, data: {
    material_type: string
    title?: string
    content_text?: string
    provider?: string
    status?: string
  }) => v2Api.post<{ id: string; material_type: string; status: string; file_hash: string }>(
    `/projects/${projectId}/legal-assets/materials`,
    data,
  ),

  checkRights: (projectId: string) =>
    v2Api.get<RightsCheckResult>(`/projects/${projectId}/legal-assets/rights-check`),

  getExportGate: (projectId: string) =>
    v2Api.get<RightsCheckResult>(`/projects/${projectId}/legal-assets/export-gate`),

  getAiStatement: (projectId: string) =>
    v2Api.get<{ content: string }>(`/projects/${projectId}/legal-assets/ai-statement`),

  createPackage: (projectId: string, packageType: string) =>
    v2Api.post<EvidencePackage>(`/projects/${projectId}/legal-assets/packages`, {
      package_type: packageType,
    }),
}
