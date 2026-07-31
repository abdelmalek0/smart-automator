import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createProject,
  createProjectTask,
  deleteProject,
  deleteProjectTask,
  listProjects,
  updateProject,
} from '@/api'
import type { Project, ProjectTask } from '@/types'

const QUERY_KEY = ['projects'] as const

export function useProjects() {
  const queryClient = useQueryClient()
  const { data: projects = [], isLoading, error } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: listProjects,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: QUERY_KEY })

  const createProjectMutation = useMutation({
    mutationFn: (payload: { name: string; url?: string; context_prompt?: string }) =>
      createProject(payload),
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
      context_prompt?: string
    }) => updateProject(projectId, payload),
    onSuccess: invalidate,
  })

  const deleteProjectMutation = useMutation({
    mutationFn: (projectId: string) => deleteProject(projectId),
    onSuccess: invalidate,
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

  const removeTaskMutation = useMutation({
    mutationFn: ({ projectId, taskId }: { projectId: string; taskId: string }) =>
      deleteProjectTask(projectId, taskId),
    onSuccess: invalidate,
  })

  return {
    projects,
    isLoading,
    error,
    createProject: createProjectMutation.mutateAsync,
    updateProject: updateProjectMutation.mutateAsync,
    deleteProject: deleteProjectMutation.mutateAsync,
    addTaskToProject: addTaskMutation.mutateAsync,
    removeTaskFromProject: removeTaskMutation.mutateAsync,
  }
}
