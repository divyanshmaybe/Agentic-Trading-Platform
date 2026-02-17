/**
 * Utility functions for generating usernames
 */

/**
 * Slugify a string to make it URL-safe
 * - Converts to lowercase
 * - Replaces spaces and special characters with hyphens
 * - Removes consecutive hyphens
 * - Trims hyphens from start/end
 */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '') // Remove special characters
    .replace(/[\s_-]+/g, '-') // Replace spaces, underscores with single hyphen
    .replace(/^-+|-+$/g, ''); // Remove leading/trailing hyphens
}

/**
 * Generate a username from user's first name, last name, and organization name
 * Format: firstname-lastname-orgname (e.g., "john-doe-acmecorp")
 * 
 * @param firstName - User's first name
 * @param lastName - User's last name
 * @param orgName - Organization name
 * @returns URL-friendly username
 */
export function generateUsername(
  firstName: string,
  lastName: string,
  orgName: string
): string {
  const slugifiedFirstName = slugify(firstName);
  const slugifiedLastName = slugify(lastName);
  const slugifiedOrgName = slugify(orgName);

  return `${slugifiedFirstName}-${slugifiedLastName}-${slugifiedOrgName}`;
}

/**
 * Validate username format
 * - Must be 3-50 characters
 * - Only alphanumeric and hyphens
 * - Cannot start or end with hyphen
 */
export function isValidUsername(username: string): boolean {
  const usernameRegex = /^[a-z0-9]+(-[a-z0-9]+)*$/;
  return (
    username.length >= 3 &&
    username.length <= 50 &&
    usernameRegex.test(username)
  );
}

