<script lang="ts">
  import { base } from '$app/paths';
  import { siteUrl } from '$lib/seo';
</script>

<svelte:head>
  <title>About this projection</title>
  <meta name="description" content="Authors, data credits, corrections policy and update schedule for the 2026 Senate county-level projection." />
  <link rel="canonical" href="{siteUrl}{base}/about" />
</svelte:head>

<div class="wrap prose">
  <h1>About</h1>
  <h2>What this is</h2>
  <p>
    An independent, open-source county-level projection of the 2026 U.S. Senate races. It is a pre-election projection:
    <strong>not an official result</strong>, not a poll, and not a prediction of any individual county's margin to the decimal.
    See the <a href="{base}/methodology">methodology</a> for how every number is produced.
  </p>
  <h2>Authors and contact</h2>
  <p>Maintained by the repository owner. Report problems through the project's issue tracker on GitHub.</p>
  <h2>Data credits</h2>
  <ul>
    <li>U.S. Census Bureau: American Community Survey and CVAP tables; cartographic boundary files.</li>
    <li>MIT Election Data and Science Lab (MEDSL): county-level presidential returns.</li>
    <li>Pollster releases and public poll compilations for generic-ballot and race polling; individual pollsters are credited in each state's poll list.</li>
    <li>Wikipedia (CC BY-SA 4.0): poll tables and candidate lists used as a cross-check. Text and data drawn from Wikipedia are reused under the same licence.</li>
    <li>Map geometry: <a href="https://github.com/topojson/us-atlas">us-atlas</a> (derived from Census Bureau shapefiles).</li>
  </ul>
  <h2>Corrections policy</h2>
  <p>Factual errors (candidate names, party labels, data mis-entry) are corrected as soon as they are verified and logged on the methodology page changelog. Model choices are not changed in response to individual results.</p>
  <h2>Update schedule</h2>
  <p>The projection is rebuilt from fresh inputs every six hours until the pre-election freeze (2026-11-03 06:00 local), after which it is not updated.</p>
  <h2>Disclaimer</h2>
  <p>Probabilities describe model uncertainty and are not forecasts of margins. Nothing here is an official election result or advice.</p>
</div>

<style>
  .prose { max-width: 760px; }
  .prose :global(li) { margin-bottom: 0.4rem; }
</style>
