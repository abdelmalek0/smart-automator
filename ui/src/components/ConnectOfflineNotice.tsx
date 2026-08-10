interface Props {
  message?: string
  className?: string
}

export default function ConnectOfflineNotice({
  message = 'Connect is offline. Log in to the Connect app to start runs.',
  className = '',
}: Props) {
  return (
    <p
      className={`text-sm text-amber-700 dark:text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2 ${className}`.trim()}
      role="status"
    >
      {message}
    </p>
  )
}
