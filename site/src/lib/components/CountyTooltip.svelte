<script lang="ts">
  import type { TooltipContent } from '$lib/tooltip';

  interface Props {
    content: TooltipContent | null;
    x?: number;
    y?: number;
    /** pinned = tap/click sheet with a "View state" link (bottom sheet on narrow screens) */
    pinned?: boolean;
    onclose?: () => void;
    containerWidth?: number;
  }
  let { content, x = 0, y = 0, pinned = false, onclose, containerWidth = 600 }: Props = $props();
  const left = $derived(Math.min(Math.max(8, x + 14), Math.max(8, containerWidth - 300)));
</script>

{#if content}
  <div
    class="tip"
    class:pinned
    role={pinned ? 'dialog' : 'tooltip'}
    aria-label={pinned ? content.title : undefined}
    style:left={pinned ? undefined : `${left}px`}
    style:top={pinned ? undefined : `${y + 14}px`}
  >
    <h3>{content.title}</h3>
    <dl>
      {#each content.rows as r}
        <div><dt>{r.label}</dt><dd>{r.value}</dd></div>
      {/each}
    </dl>
    {#if pinned}
      <p class="actions">
        <a href={content.stateLink}>View state</a>
        <button type="button" class="link" onclick={() => onclose?.()}>Close</button>
      </p>
    {/if}
  </div>
{/if}

<style>
  .tip { position: absolute; z-index: 5; width: 290px; background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: var(--radius); padding: 0.6rem 0.75rem; box-shadow: 0 4px 16px rgb(0 0 0 / 0.25); pointer-events: none; font-size: 0.85rem; }
  .tip.pinned { pointer-events: auto; }
  h3 { font-size: 0.95rem; margin: 0 0 0.35rem; }
  dl { margin: 0; }
  dl div { display: flex; justify-content: space-between; gap: 0.75rem; padding: 1px 0; }
  dt { color: var(--muted); }
  dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
  .actions { margin: 0.5rem 0 0; display: flex; justify-content: space-between; }
  @media (max-width: 640px) {
    .tip.pinned { position: fixed; left: 0; right: 0; bottom: 0; top: auto; width: auto; border-radius: 14px 14px 0 0; padding: 1rem var(--gutter) 1.25rem; font-size: 0.95rem; }
  }
</style>
