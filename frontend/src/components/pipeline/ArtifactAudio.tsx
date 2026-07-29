interface ArtifactAudioProps {
  label: string
  src: string | null | undefined
  /** Remount the player when this changes (e.g. after re-running a stage). */
  reloadKey?: string | number
}

/** `<audio>` wrapper for a resolved `/api/media?path=...` URL — migrated from webui/components/artifacts.py. */
export function ArtifactAudio({ label, src, reloadKey }: ArtifactAudioProps) {
  return (
    <div className="space-y-1.5">
      <p className="text-sm font-medium">{label}</p>
      {src ? (
        <audio
          key={reloadKey ?? src}
          controls
          src={src}
          className="w-full"
          data-testid="artifact-audio"
        />
      ) : (
        <p className="text-xs text-muted-foreground">暂无产物</p>
      )}
    </div>
  )
}
