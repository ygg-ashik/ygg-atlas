import { describe, expect, it } from 'vitest';
import { artifactFilename, toCsv } from './csv';

describe('csv', () => {
  it('quotes cells with commas, quotes and newlines; nulls are empty', () => {
    expect(
      toCsv(
        ['Label', 'Value'],
        [
          ['b2b, corp', 1000],
          ['say "hi"', null],
          ['a\nb', 2],
        ],
      ),
    ).toBe('Label,Value\r\n"b2b, corp",1000\r\n"say ""hi""",\r\n"a\nb",2');
  });
  it('neutralizes spreadsheet formula injection', () => {
    expect(toCsv(['x'], [['=HYPERLINK("evil")'], ['+1'], ['-2'], ['@a']])).toBe(
      'x\r\n"\'=HYPERLINK(""evil"")"\r\n\'+1\r\n\'-2\r\n\'@a',
    );
  });
  it('builds a safe filename', () => {
    expect(artifactFilename('Revenue: breakdown / Q3')).toBe('revenue-breakdown-q3.csv');
  });
});
