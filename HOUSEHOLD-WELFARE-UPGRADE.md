# Household & Expanded Welfare Upgrade

## Cover structure

Each Active welfare alumnus is the **Principal Member**.

The following people can be registered under that principal member:

- one spouse (group rules can enforce this operationally)
- children
- mother
- father

New household records are tracked separately and may require committee verification before claims can be approved.

## Support types

The welfare engine now supports:

1. Bereavement
2. Serious illness
3. Hospitalisation
4. Accident / emergency

The committee sets rules rather than hard-coding financial promises into the software.

Each rule specifies:

- relationship: Principal / Spouse / Child / Mother / Father
- benefit amount
- waiting period
- maximum claims per person per year
- evidence / eligibility notes

## Recommended governance approach

For illness support, avoid covering every outpatient visit or minor illness. Define a narrow trigger such as a documented major diagnosis, hospital admission, surgery, or serious accident. Decide the proof required, the fixed benefit, and the annual claim limit before accepting real contributions.

## Deployment

This version adds new PostgreSQL tables (`household_member`, `welfare_rule`, `support_case`). `db.create_all()` will create them on the existing database; existing member/contribution/opportunity tables are not altered.
