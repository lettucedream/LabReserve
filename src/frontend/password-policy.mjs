export const PASSWORD_HINT = "Usa da 8 a 128 caratteri, con almeno una maiuscola, un numero e un simbolo speciale.";

export function passwordError(value) {
  const password = value.normalize("NFC");
  return [...password].length >= 8 && [...password].length <= 128
    && /\p{Lu}/u.test(password) && /\p{Nd}/u.test(password) && /[\p{P}\p{S}]/u.test(password)
    ? "" : PASSWORD_HINT;
}
