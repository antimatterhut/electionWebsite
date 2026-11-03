// State FIPS -> postal abbreviation and name (shared by the data/topology/OG scripts).
export const STATES = {
  '01': ['AL', 'Alabama'], '02': ['AK', 'Alaska'], '04': ['AZ', 'Arizona'], '05': ['AR', 'Arkansas'],
  '06': ['CA', 'California'], '08': ['CO', 'Colorado'], '09': ['CT', 'Connecticut'], '10': ['DE', 'Delaware'],
  '11': ['DC', 'District of Columbia'], '12': ['FL', 'Florida'], '13': ['GA', 'Georgia'], '15': ['HI', 'Hawaii'],
  '16': ['ID', 'Idaho'], '17': ['IL', 'Illinois'], '18': ['IN', 'Indiana'], '19': ['IA', 'Iowa'],
  '20': ['KS', 'Kansas'], '21': ['KY', 'Kentucky'], '22': ['LA', 'Louisiana'], '23': ['ME', 'Maine'],
  '24': ['MD', 'Maryland'], '25': ['MA', 'Massachusetts'], '26': ['MI', 'Michigan'], '27': ['MN', 'Minnesota'],
  '28': ['MS', 'Mississippi'], '29': ['MO', 'Missouri'], '30': ['MT', 'Montana'], '31': ['NE', 'Nebraska'],
  '32': ['NV', 'Nevada'], '33': ['NH', 'New Hampshire'], '34': ['NJ', 'New Jersey'], '35': ['NM', 'New Mexico'],
  '36': ['NY', 'New York'], '37': ['NC', 'North Carolina'], '38': ['ND', 'North Dakota'], '39': ['OH', 'Ohio'],
  '40': ['OK', 'Oklahoma'], '41': ['OR', 'Oregon'], '42': ['PA', 'Pennsylvania'], '44': ['RI', 'Rhode Island'],
  '45': ['SC', 'South Carolina'], '46': ['SD', 'South Dakota'], '47': ['TN', 'Tennessee'], '48': ['TX', 'Texas'],
  '49': ['UT', 'Utah'], '50': ['VT', 'Vermont'], '51': ['VA', 'Virginia'], '53': ['WA', 'Washington'],
  '54': ['WV', 'West Virginia'], '55': ['WI', 'Wisconsin'], '56': ['WY', 'Wyoming']
};
export const FIPS_BY_PO = Object.fromEntries(Object.entries(STATES).map(([f, [po]]) => [po, f]));
export const NAME_BY_PO = Object.fromEntries(Object.values(STATES));

/** Minimal RFC-4180 CSV parser (quoted fields, doubled quotes). Returns an array of objects keyed by the header. */
export function parseCsv(text) {
  const rows = [];
  let row = [], f = '', q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { f += '"'; i++; } else q = false; } else f += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(f); f = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(f); f = ''; if (row.length > 1 || row[0] !== '') rows.push(row); row = [];
    } else f += c;
  }
  if (f !== '' || row.length) { row.push(f); rows.push(row); }
  const [head, ...body] = rows;
  return body.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ''])));
}
