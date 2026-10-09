// Public interface of the admin feature.
// PLACEHOLDER: F8 replaces the audit page.
import { createElement } from 'react';
import { PlaceholderPage } from './placeholder-page';

export { UsersPage } from './components/users-page';
export { UserDetailPage } from './components/user-detail-page';
export { GroupsPage } from './components/groups-page';
export { GroupDetailPage } from './components/groups-page';
export { AdminRequestsPage } from './components/requests-page';
export const AuditPage = () => createElement(PlaceholderPage, { title: 'Audit' });
