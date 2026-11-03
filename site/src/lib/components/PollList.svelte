<script lang="ts">
  import { margin } from '$lib/format';
  import type { PollRow } from '$lib/data/types';

  let { polls }: { polls: PollRow[] } = $props();
</script>

<section class="panel" aria-labelledby="pl-h">
  <h2 id="pl-h">Recent polls</h2>
  {#if polls.length === 0}
    <p class="muted">No recent polls for this race.</p>
  {:else}
    <table>
      <thead><tr><th scope="col">Pollster</th><th scope="col">Field end</th><th scope="col" class="num">n</th><th scope="col">Pop.</th><th scope="col" class="num">Margin</th></tr></thead>
      <tbody>
        {#each polls as p}
          <tr><th scope="row">{p.pollster}</th><td><time datetime={p.end}>{p.end}</time></td><td class="num">{p.n}</td><td>{p.pop}</td><td class="num">{margin(p.margin)}</td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
