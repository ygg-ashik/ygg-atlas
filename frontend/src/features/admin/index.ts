// Public interface of the admin feature.
// PLACEHOLDERS: F7 replaces the requests queue and F8 the audit page.
import { createElement } from 'react';
import { PlaceholderPage } from './placeholder-page';

export { UsersPage } from './components/users-page';
export { UserDetailPage } from './components/user-detail-page';
export { GroupsPage } from './components/groups-page';
export { GroupDetailPage } from './components/groups-page';
export const AdminRequestsPage = () => createElement(PlaceholderPage, { title: 'Access requests' });
export const AuditPage = () => createElement(PlaceholderPage, { title: 'Audit' });
