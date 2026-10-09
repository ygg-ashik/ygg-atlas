// Public interface of the account feature (self-service).
// PLACEHOLDER: F9 replaces Tokens.
import { createElement } from 'react';
import { PlaceholderPage } from './placeholder-page';

export { MyAccessPage } from './components/my-access-page';
export { MyRequestsPage } from './components/requests-page';
export { NewRequestPage } from './components/new-request-page';
export const TokensPage = () =>
  createElement(PlaceholderPage, { title: 'Tokens & connected apps' });
