<script lang="ts">
  import { base } from '$app/paths';
  import { page } from '$app/state';
</script>

<svelte:head><title>{page.status} - 2026 Senate projection</title></svelte:head>
<div class="wrap">
  <h1>{page.status === 404 ? 'Page not found' : 'Something went wrong'}</h1>
  <p>{page.error?.message}</p>
  <p><a href="{base}/">Back to the national projection</a></p>
</div>
