import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createWebsite,
  createWebsiteTask,
  deleteWebsite,
  deleteWebsiteTask,
  listWebsites,
  updateWebsite,
} from '@/api'
import type { Website, WebsiteTask } from '@/types'

const QUERY_KEY = ['websites'] as const

export function useWebsites() {
  const queryClient = useQueryClient()
  const { data: websites = [], isLoading, error } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: listWebsites,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: QUERY_KEY })

  const createWebsiteMutation = useMutation({
    mutationFn: (payload: { name: string; url?: string; context_prompt?: string }) =>
      createWebsite(payload),
    onSuccess: invalidate,
  })

  const updateWebsiteMutation = useMutation({
    mutationFn: ({
      websiteId,
      ...payload
    }: {
      websiteId: string
      name?: string
      url?: string
      context_prompt?: string
    }) => updateWebsite(websiteId, payload),
    onSuccess: invalidate,
  })

  const deleteWebsiteMutation = useMutation({
    mutationFn: (websiteId: string) => deleteWebsite(websiteId),
    onSuccess: invalidate,
  })

  const addTaskMutation = useMutation({
    mutationFn: ({
      websiteId,
      ...payload
    }: {
      websiteId: string
    } & Omit<WebsiteTask, 'id'>) => createWebsiteTask(websiteId, payload),
    onSuccess: invalidate,
  })

  const removeTaskMutation = useMutation({
    mutationFn: ({ websiteId, taskId }: { websiteId: string; taskId: string }) =>
      deleteWebsiteTask(websiteId, taskId),
    onSuccess: invalidate,
  })

  return {
    websites,
    isLoading,
    error,
    createWebsite: createWebsiteMutation.mutateAsync,
    updateWebsite: updateWebsiteMutation.mutateAsync,
    deleteWebsite: deleteWebsiteMutation.mutateAsync,
    addTaskToWebsite: addTaskMutation.mutateAsync,
    removeTaskFromWebsite: removeTaskMutation.mutateAsync,
  }
}
