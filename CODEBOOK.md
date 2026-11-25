# Codebook 1.1

This file is generated from `webapp/core.py`, which is what the application enforces. The same definitions appear under each field in the coding form and on the Help page.

## Units

- **Video**: one upload. Format, genre, party favoured, authenticity cues and disclosure are coded per video.
- **Persona**: each person who speaks or is interviewed. Number personas 1, 2, 3 in order of appearance, so independent coders' personas can be matched.

## Coding rules

1. Watch the whole video at least once before coding.
2. Code what a viewer would perceive. Visible markers and what the person says are coded separately.
3. Never infer religion from a name.
4. A party name or symbol shown without support is not an endorsement.
5. Leave nothing as missing when you submit.

## Missing, unknown, uncertain, not applicable

| Value | Meaning |
|---|---|
| missing | Not coded yet. Counts as incomplete. Replace it before submitting. |
| unknown | You checked, and the video does not show or say this. This is a real answer. |
| uncertain | You can see something, but you cannot choose between the categories. |
| not applicable | The question does not apply to this video or person. |

For reliability, *missing* counts as incomplete, *not applicable* is left out of alpha, and *unknown* and *uncertain* are kept as real categories.

## Eligibility

A video is eligible when at least one AI-generated person, presented as an ordinary member of the public, expresses a political view about Bangladesh's 2026 election, and the upload falls inside the study period (15 June 2025 to 12 February 2026). Excluded videos need one of these reasons:

- outside study period
- not election related
- no speaking persona
- real person deepfake
- cartoon or animation
- genuine footage
- repost of included video
- not bangladesh context
- cannot be viewed
- other

## Video-level variables

| Variable | Values | Definition |
|---|---|---|
| format | street interview, single testimonial, montage, skit, news style, other, unknown | How the video is built. A street interview has an interviewer and passers-by; a montage joins several short clips. |
| genre | persuasive, satirical, other, unknown | Persuasive means it asks viewers to support or reject a party. Satirical means it is played for laughs. |
| party favoured | bnp, jamaat, ncp, awami league, jatiya party, other party, multiple, none, unknown | The party the video as a whole supports. Use none if no party is supported; multiple if more than one. |
| interviewer | yes, no, unknown | Is an interviewer or reporter visible or heard? |
| news brand | yes, no, unknown | Is there a microphone, logo or banner styled like a news channel? |
| captions | yes, no, unknown | Are there on-screen captions or subtitles? |
| uniforms | yes, no, unknown | Does any person wear a uniform (police, army, school, professional)? |
| regional dialect | yes, no, unknown | Does any speaker use a clearly regional Bangla dialect rather than standard Bangla? |
| production artifacts | yes, no, unknown | Visible or audible generation artifacts: merged fingers, warped text, lip-sync drift, flicker. |
| authenticity | free text | Free text. Other cues that make the people look real or authoritative. |
| frame | free text | Free text. The problem defined, who is blamed, and the remedy proposed. |
| notes | free text | Free text. Anything else the adjudicator should know. |

## Persona-level variables

| Variable | Values | Definition |
|---|---|---|
| gender **(critical for reliability)** | male, female, other, unknown | Apparent gender as presented. Code what a viewer would perceive. |
| age **(critical for reliability)** | child, young adult, middle aged, elderly, unknown | Apparent age group as presented. |
| setting | rural, urban, unknown | Where the person is shown: village or field (rural) versus city street, shop or office (urban). |
| disability marker | yes, no, unknown | A visible disability marker such as a wheelchair, crutch or white cane. |
| visible religion | muslim, hindu, christian, buddhist, other, no visible marker, unknown | Religion suggested by visible markers only: cap, beard, hijab, sindoor, tilak, cross. Never infer from a name. |
| stated religion | muslim, hindu, christian, buddhist, other, not stated | Religion the person says in speech. Use not_stated if they do not say it. |
| visible occupation | farmer, rickshaw or transport, shopkeeper or vendor, labourer, student, teacher, professional, police or security, religious cleric, homemaker, journalist, other, no visible marker, unknown | Occupation suggested by clothing, tools or setting, such as a rickshaw, plough or police uniform. |
| stated occupation | farmer, rickshaw or transport, shopkeeper or vendor, labourer, student, teacher, professional, police or security, religious cleric, homemaker, journalist, other, not stated | Occupation the person says in speech. Use not_stated if they do not say it. |
| visible markers | free text | Free text. List the visible markers you relied on. |
| stated identity | free text | Free text. Identity the person states: occupation, region, community. |
| transcript bn | free text | Free text. What the person says, in Bangla script, as spoken. |
| endorses party **(critical for reliability)** | bnp, jamaat, ncp, awami league, jatiya party, other party, multiple, none, unknown | Party this person explicitly supports. A name or symbol shown without support is none. |
| attacks party | bnp, jamaat, ncp, awami league, jatiya party, other party, multiple, none, unknown | Party this person explicitly criticises. Use none if no party is criticised. |
| issues | free text | Free text. Policy issues raised, separated by semicolons. |
| factual claim | yes, no, unknown | Does the person make a checkable factual claim (a number, event or record)? |
| factual claim text | free text | Free text. The claim, in their words. |
| emotion | none, fear, anger, hope, pride, humour, grievance, other, unknown | The main emotional appeal in what the person says. |
| voice | personal, collective, none, unknown | Personal: "I will vote". Collective: "people like us support". None: no endorsement. |
| dialect | free text | Free text. Name the dialect if one is clear. |
| notes | free text | Free text. Anything else the adjudicator should know. |

## Origin verification levels

| Level | Basis | Use |
|---|---|---|
| 1 | A fact-checking organisation examined this clip and rated the speaking persona(s) AI-generated. Evidence must cover every speaking persona. | Main corpus |
| 2 | YouTube's "altered or synthetic" label or an explicit creator disclosure that covers every speaking persona. | Main corpus |
| 3 | Two trained coders independently judged the persona(s) AI-generated using the artifact checklist. | Reported separately |
| 0 | No qualifying evidence yet. | Not in the corpus |

