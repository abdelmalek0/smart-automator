import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createProject,
  createProjectTask,
  deleteProject,
  deleteProjectTask,
  importProject,
  importProjectTests,
  listProjects,
  updateProject,
  updateProjectTask,
} from '@/api'
import type { ProjectPack } from '@/lib/project-pack'
import type { ProjectTestsPack } from '@/lib/project-tests-pack'
import type { ProjectTask } from '@/types'

const QUERY_KEY = ['projects'] as const

export function useProjects() {
  const queryClient = useQueryClient()
  const { data: projects = [], isLoading, error, isFetching } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: listProjects,
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: QUERY_KEY })
  }

  const invalidateProjectsAndRuns = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: ['runs'] }),
    ])
  }

  const createProjectMutation = useMutation({
    mutationFn: (payload: {
      name: string
      url?: string
      description?: string
      context_prompt?: string
    }) => createProject(payload),
    onSuccess: invalidate,
  })

  const updateProjectMutation = useMutation({
    mutationFn: ({
      projectId,
      ...payload
    }: {
      projectId: string
      name?: string
      url?: string
      description?: string
      context_prompt?: string
    }) => updateProject(projectId, payload),
    onSuccess: invalidate,
  })

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: invalidateProjectsAndRuns,
  })

  const addTaskMutation = useMutation({
    mutationFn: ({
      projectId,
      ...payload
    }: {
      projectId: string
    } & Omit<ProjectTask, 'id'>) => createProjectTask(projectId, payload),
    onSuccess: invalidate,
  })

  const updateTaskMutation = useMutation({
    mutationFn: ({
      projectId,
      taskId,
      ...payload
    }: {
      projectId: string
      taskId: string
    } & Partial<Omit<ProjectTask, 'id'>>) => updateProjectTask(projectId, taskId, payload),
    onSuccess: invalidate,
  })

  const removeTaskMutation = useMutation({
    mutationFn: ({ projectId, taskId }: { projectId: string; taskId: string }) =>
      deleteProjectTask(projectId, taskId),
    onSuccess: invalidateProjectsAndRuns,
  })

  const importTestsMutation = useMutation({
    mutationFn: ({
      projectId,
      pack,
    }: {
      projectId: string
      pack: ProjectTestsPack
    }) => importProjectTests(projectId, pack),
    onSuccess: invalidate,
  })

  const importProjectMutation = useMutation({
    mutationFn: (pack: ProjectPack) => importProject(pack),
    onSuccess: invalidate,
  })

  return {
    projects,
    isLoading,
    isFetching,
    error,
    createProject: createProjectMutation.mutateAsync,
    updateProject: updateProjectMutation.mutateAsync,
    deleteProject: deleteProjectMutation.mutateAsync,
    addTaskToProject: addTaskMutation.mutateAsync,
    updateProjectTask: updateTaskMutation.mutateAsync,
    removeTaskFromProject: removeTaskMutation.mutateAsync,
    importProjectTests: importTestsMutation.mutateAsync,
    importProject: importProjectMutation.mutateAsync,
    isCreating: createProjectMutation.isPending,
    isUpdating: updateProjectMutation.isPending,
    isDeleting: deleteProjectMutation.isPending,
    isSavingTask: addTaskMutation.isPending || updateTaskMutation.isPending,
    isRemovingTask: removeTaskMutation.isPending,
    isImportingTests: importTestsMutation.isPending,
    isImportingProject: importProjectMutation.isPending,
  }
}
