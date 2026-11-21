import { expect, test } from 'vitest';
import { checkout } from './checkout';
test.each(['buyer', 'admin'])('checkout accepts %s auth token', role => {
  expect(checkout(role)).toBe(true);
});
