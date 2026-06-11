/**
 * Aureon Global - Onboarding Form + Onboarding Doc Generator
 *
 * v2.1 changes:
 *   - Fixed encoding: all separators are pure ASCII (no garbled emails)
 *   - createOnboardingDoc() builds a Google Doc with all the questions a client
 *     needs to fill in (mirrors the form) PLUS a practical implementation section
 *     so they understand what comes after the questionnaire.
 */

// ============================================================
// FORM SUBMISSION HANDLER (fixed ASCII formatting)
// ============================================================
function onAureonFormSubmit(e) {
  var itemResponses = e.response.getItemResponses();
  var body = 'New Aureon onboarding response\n';
  body += '===============================\n\n';

  itemResponses.forEach(function (itemResponse) {
    var title = itemResponse.getItem().getTitle();
    var answer = itemResponse.getResponse();
    if (Array.isArray(answer)) answer = answer.join(', ');
    body += title + ':\n' + (answer || '(not provided)') + '\n\n';
  });

  var respondentEmail = e.response.getRespondentEmail();
  if (respondentEmail) {
    body += '---\n';
    body += 'Respondent email: ' + respondentEmail + '\n';
  }
  body += 'Submitted: ' + new Date().toUTCString() + '\n';

  MailApp.sendEmail({
    to: 'info@aureonglobal.de',
    subject: 'Aureon onboarding response received',
    body: body
  });
}

// ============================================================
// ONBOARDING DOC GENERATOR
// Creates a Google Doc with the same questions as the form, plus
// practical implementation details so the client understands the full path.
// ============================================================
function createOnboardingDoc() {
  var doc = DocumentApp.create('Aureon Global Onboarding Checklist');
  var body = doc.getBody();
  body.clear();

  var H1 = DocumentApp.ParagraphHeading.HEADING1;
  var H2 = DocumentApp.ParagraphHeading.HEADING2;
  var H3 = DocumentApp.ParagraphHeading.HEADING3;
  var CENTER = DocumentApp.HorizontalAlignment.CENTER;

  // ----- Cover -----
  body.appendParagraph('Aureon Global Onboarding Checklist').setHeading(H1).setAlignment(CENTER);
  body.appendParagraph('This questionnaire is for the free email marketing offer from Aureon Global.').setAlignment(CENTER).editAsText().setItalic(true);
  body.appendParagraph('');
  body.appendParagraph('A short ten minute fill in so we can draft your pilot agreement and configure the engine for your domain. Type your answers under each question. Send the completed doc back to info@aureonglobal.de or share it directly with that account.');
  body.appendParagraph('');

  // Helper to add a question
  function addQuestion(num, title, explanation, multiline) {
    body.appendParagraph(num + '  ' + title).setHeading(H3);
    body.appendParagraph(explanation).editAsText().setItalic(true).setForegroundColor('#555555');
    body.appendParagraph('');
    if (multiline) {
      body.appendParagraph('Answer:');
      body.appendParagraph('___________________________________________________________');
      body.appendParagraph('___________________________________________________________');
      body.appendParagraph('___________________________________________________________');
    } else {
      body.appendParagraph('Answer: ___________________________________________________');
    }
    body.appendParagraph('');
  }

  // ----- Section 1: Your company -----
  body.appendParagraph('1.  Your Company').setHeading(H2);
  body.appendParagraph('Basic legal info for the agreement.').editAsText().setItalic(true);
  body.appendParagraph('');

  addQuestion('1.1', 'Full registered company name',
    'This goes on the contract as the legal counterparty. We need it exactly as it appears on Companies House or your local company register, including the suffix like Limited, GmbH, LLC.', false);

  addQuestion('1.2', 'Company registration number',
    'The official number from your company register (8 digits for UK Companies House, similar elsewhere). We use it to identify your legal entity unambiguously on the agreement. If you do not have it handy, we can look it up for you.', false);

  addQuestion('1.3', 'Country of incorporation',
    'Where your company is legally registered, for example England and Wales, Delaware USA, Germany. This tells us which legal framework applies on your side.', false);

  addQuestion('1.4', 'Registered office address',
    'The official address on your company filing. Goes into the parties block of the contract and is used for any formal notice by post. If your trading address is different, we only need the registered one.', true);

  addQuestion('1.5', 'Who is signing on your side? Name, title, email.',
    'Whoever has authority to sign on your side, usually the CEO, founder, or a Director. We send the signature link via Dropbox Sign to the email you give us.', false);

  addQuestion('1.6', 'Email for formal notices',
    'Where to send any formal notices about the agreement, things like renewals, terminations, material changes. Can be the same as the signer above, or a dedicated info@, legal@, or your direct one.', false);

  // ----- Section 2: Sending setup -----
  body.appendParagraph('2.  Sending Setup').setHeading(H2);
  body.appendParagraph('We send under your own domain.').editAsText().setItalic(true);
  body.appendParagraph('');

  addQuestion('2.1', 'Which domain should we send under?',
    'Your main brand domain, for example yourcompany.com. We provision up to ten sending subdomains underneath it (outreach.yourcompany.com, hi.yourcompany.com, etc.) so emails go out under your brand. The sending reputation belongs to you, not us.', false);

  addQuestion('2.2', 'Do you control DNS for that domain?',
    'DNS is the system that controls how your domain works. We need to add four small text records to it for each subdomain so email providers know our sends are authorised. We just want to know who handles DNS on your side, so we know who to ask. Options: (a) Yes, in house, (b) Our web agency handles it, (c) Not sure, will find out.', false);

  addQuestion('2.3', 'DNS handover method',
    'Two paths, both fine. Option 1: you give us temporary access to your DNS provider (Cloudflare, GoDaddy, Route 53, etc.) and we publish the records ourselves in about ten minutes. Option 2: you publish them yourself using our written instructions. Self publishing keeps full control on your side but takes a bit longer.', false);

  // ----- Section 3: Where booked intros land -----
  body.appendParagraph('3.  Where Booked Intros Land').setHeading(H2);
  body.appendParagraph('');

  addQuestion('3.1', 'Where should we route positive replies?',
    'When a prospect replies asking for a demo, we forward that reply (plus a one page brief on the company) to one endpoint of your choice within sixty minutes. A Calendly or similar booking link is fastest because the prospect self serves. A personal inbox works too. Whichever you can action quickest.', false);

  addQuestion('3.2', 'Who takes the intro calls?',
    'The person who actually shows up to the intro call. We send them a one page brief beforehand with the prospect company info, the trigger event we used to reach out, and the buyer role, so they walk in already prepared.', false);

  // ----- Section 4: Your ICP -----
  body.appendParagraph('4.  Your ICP').setHeading(H2);
  body.appendParagraph('');

  addQuestion('4.1', 'Describe your ideal customer',
    'The kind of company you want as a customer, as specific as you can make it. At minimum cover: industry or sector, company size (employees or revenue band), maturity stage (early, scale up, enterprise), and geography. The tighter you describe it, the higher the conversion rate.', true);

  addQuestion('4.2', 'Best converting buyer titles',
    'The job titles of the people who actually say yes to your product. If you have done any sales already, who closes fastest? CRO, VP Sales, Head of Enablement, RevOps Lead, Procurement, founder, etc. Comma separated. We weight the outbound to land in front of these titles first.', false);

  addQuestion('4.3', 'Companies or sectors to exclude',
    'Companies we should never contact, in any format you have them. Current customers, competitors, anyone you have already pitched in the last six months, anyone on a do not contact list. Drop them in here and we suppress the entire engine from touching them.', true);

  addQuestion('4.4', 'Any buying signals that matter for your category',
    'Buying signals are public events that suggest a company is ready to act now. The standard ones are new funding rounds, a new VP or CRO joining, sales hiring sprees, competitor contracts coming up for renewal. If you know of category specific signals (a vendor migration, a regulation, an industry event), tell us and we will scan for those too.', true);

  // ----- Section 5: Timing -----
  body.appendParagraph('5.  Timing').setHeading(H2);
  body.appendParagraph('');

  addQuestion('5.1', 'Earliest DNS handover date',
    'Once DNS is set, sending goes live within seven days. The three month pilot clock starts on the day DNS is set, not the day you sign. Give us your realistic earliest date so we both know when first emails go out.', false);

  addQuestion('5.2', 'Best slot for the 15 minute kickoff call',
    'We run a 15 minute call within two working days of the agreement being signed. On it we confirm your ICP, the reply routing endpoint, and any last tweaks. Give us a day, time, and timezone that works and we will send a calendar invite to lock it in.', false);

  // ----- Practical implementation -----
  body.appendPageBreak();
  body.appendParagraph('Practical Implementation').setHeading(H1).setAlignment(CENTER);
  body.appendParagraph('What happens between signing and first sends, and what we commit to during the pilot.').setAlignment(CENTER).editAsText().setItalic(true);
  body.appendParagraph('');

  body.appendParagraph('What we need from you to start').setHeading(H2);

  body.appendParagraph('Signed pilot agreement').setHeading(H3);
  body.appendParagraph('We send the agreement via Dropbox Sign once this questionnaire is complete. Two to three month pilot, no fees, pricing revisited after the pilot. Your accounts, reputation, and data stay with you (within the limits set out in the agreement).');
  body.appendParagraph('');

  body.appendParagraph('DNS access or DNS records published').setHeading(H3);
  body.appendParagraph('We need to publish four records per sending subdomain under your domain:');
  body.appendListItem('SPF (TXT) - authorises our sending IPs for your domain').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('DKIM (TXT or CNAME) - cryptographic signing key').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('DMARC (TXT) - alignment and reporting policy').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Click tracking CNAME - link tracking endpoint').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendParagraph('Either: (a) you grant us temporary DNS access (Cloudflare, GoDaddy, Route 53, etc.) and we publish in 10 minutes, or (b) you publish them yourself using our written instructions. Either is fine.');
  body.appendParagraph('');

  body.appendParagraph('15 minute kickoff call').setHeading(H3);
  body.appendParagraph('Within 2 working days of the agreement being signed. We confirm ICP, target buyer titles, sectoral exclusions, sender persona name, reply routing endpoint, and any last tweaks.');
  body.appendParagraph('');

  body.appendParagraph('Routing endpoint for booked intros').setHeading(H3);
  body.appendParagraph('A Calendly link, personal calendar, or shared inbox where we forward every positive intent reply within 60 minutes during our business hours. The reply arrives with a one page brief on the company so the call starts at minute 2, not minute 0.');
  body.appendParagraph('');

  // Timeline
  body.appendParagraph('Timeline').setHeading(H2);

  body.appendParagraph('Day 0 - Agreement and kickoff').setHeading(H3);
  body.appendParagraph('Pilot agreement signed via Dropbox Sign. 15 minute kickoff call confirms ICP, target buyer titles, the pitch angle, and who takes the booked intro calls.');

  body.appendParagraph('Day 1 - DNS and sender pool').setHeading(H3);
  body.appendParagraph('You hand us DNS access (or publish records yourself). We provision SPF, DKIM, DMARC, click tracking CNAME under up to 10 outbound subdomains. Verification under an hour.');

  body.appendParagraph('Day 2 to 3 - Account pull').setHeading(H3);
  body.appendParagraph('Signal feeds run. First batch of ICP matched accounts populates, each with employee count, funding stage, methodology mentions, trigger events, and a recommended angle.');

  body.appendParagraph('Day 4 to 7 - First sends').setHeading(H3);
  body.appendParagraph('Warmup ramps to 150 sends per day across the ten subdomain pool. First responses typically arrive between day 5 and day 10. Reply alerts route to your inbox in real time.');

  body.appendParagraph('Week 1 to 4 - Snowball warmup').setHeading(H3);
  body.appendParagraph('15 sends per subdomain per day in Week 1, 25 in Week 2, 35 in Week 3, 50 in Week 4 onward. Across the pool that lands at 500 sends per day at full ramp. Weekdays only.');

  body.appendParagraph('Month 2 to 3 - Pilot review').setHeading(H3);
  body.appendParagraph('Both products have real data by then. We sit down, look at the numbers (sends, opens, replies, intent breakdown, intros booked, conversions), and discuss pricing for continued service under a Definitive Agreement.');
  body.appendParagraph('');

  // What we commit to
  body.appendParagraph('What we commit to during the pilot').setHeading(H2);
  body.appendListItem('Send only Monday to Friday, 08:00 to 17:00 in the recipient local timezone').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Working one click unsubscribe in every email').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Honour every unsubscribe within 24 hours, suppressed permanently').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Auto pause any subdomain that exceeds 3% bounce rate in any 24 hour rolling window').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Route classified positive intent replies to your endpoint within 60 minutes during our business hours').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Deliver a weekly Monday brief on sends, opens, replies, intent classification, intros booked, bounce rate per subdomain, and operational incidents').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Notify you of any personal data breach within 72 hours of becoming aware').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Give 14 days advance notice before engaging any new sub processor that handles personal data').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Maintain GDPR Article 32 technical and organisational measures (TLS 1.2+, AES-256, MFA, daily backups, etc.)').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Provide weekly written brief, real time reply routing, full operational transparency').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendParagraph('');

  // What you need to do
  body.appendParagraph('What you need to keep doing').setHeading(H2);
  body.appendListItem('Take the booked intro calls when they hit your endpoint').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Respond to our operational queries within 2 business days during the term').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Tell us if your ICP, intro routing, or buyer titles change').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Review and approve any new sequence copy we send (3 business day silence equals approval)').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendListItem('Keep your DNS zone intact for the duration of the pilot').setGlyphType(DocumentApp.GlyphType.BULLET);
  body.appendParagraph('');

  // Footer
  body.appendParagraph('---').setAlignment(CENTER);
  body.appendParagraph('Send the completed checklist to info@aureonglobal.de or share this doc with that account.').setAlignment(CENTER);
  body.appendParagraph('Aureon Global L.L.C. | Dushkaja 20, 71000 Kacanik | Republic of Kosovo | aureonglobal.de').setAlignment(CENTER).editAsText().setForegroundColor('#777777');

  doc.saveAndClose();

  var url = doc.getUrl();
  Logger.log('=========================================================');
  Logger.log('Aureon Onboarding Checklist Google Doc created.');
  Logger.log('');
  Logger.log('URL: ' + url);
  Logger.log('=========================================================');
  Logger.log('Share this doc with prospects, or use it as a template.');

  return url;
}

// =========================================================
// FORM INTRO SECTION ADDER
// Adds a "What happens after you submit" intro section
// (timeline + commitments + responsibilities) to the TOP
// of the existing Google Form, BEFORE section 1.
// Idempotent: aborts if intro already present.
// =========================================================
function addIntroSection() {
  var FORM_ID = '1vQ3x3ygcqS8LwhJe_HiIE1oDtIfMHM5zXycDqL6ITLE';
  var form = FormApp.openById(FORM_ID);

  // Cleanup: remove any existing intro items by title (handles both
  // double-runs and the partial-failure case where items were appended
  // but moveItem threw before they were reordered).
  var introTitles = [
    'What happens after you submit',
    'Day 0 - Sign the pilot agreement',
    'Day 1 - DNS and sender pool',
    'Day 2 to 3 - Account pull',
    'Day 4 to 7 - First sends',
    'Week 1 to 4 - Snowball warmup',
    'Month 2 to 3 - Full ramp',
    'What we commit to during the pilot',
    'What you need to keep doing'
  ];
  var existingItems = form.getItems();
  var removed = 0;
  for (var k = existingItems.length - 1; k >= 0; k--) {
    if (introTitles.indexOf(existingItems[k].getTitle()) >= 0) {
      form.deleteItem(k);
      removed++;
    }
  }
  if (removed > 0) {
    Logger.log('Cleanup: removed ' + removed + ' existing intro items.');
  }

  // Build content in DISPLAY order. Each block uses SectionHeaderItem
  // so all 9 blocks stay on page 1; the existing PageBreakItem for
  // "1. Your Company" still acts as the divider into the questionnaire.
  var originalCount = form.getItems().length;
  var newItems = [];

  newItems.push(form.addSectionHeaderItem()
    .setTitle('What happens after you submit')
    .setHelpText('Before you fill in your info, here is exactly what happens once you submit. Read this in 90 seconds so you know what you are signing up for.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Day 0 - Sign the pilot agreement')
    .setHelpText('Once you submit this form we draft your pilot service agreement and send it back for signature. Pilot fees: zero euros. We carry SaaS and infrastructure costs.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Day 1 - DNS and sender pool')
    .setHelpText('You hand us DNS access or publish records yourself. We provision SPF, DKIM, DMARC, and click-tracking CNAME under up to ten outbound subdomains. Verification under an hour.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Day 2 to 3 - Account pull')
    .setHelpText('Signal feeds run. First batch of ICP-matched accounts populates, each with employee count, funding stage, methodology mentions, trigger events, and a recommended angle.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Day 4 to 7 - First sends')
    .setHelpText('Warmup ramps to 150 sends per day across the ten subdomain pool. First responses typically arrive between day 5 and day 10. Reply alerts route to your inbox in real time.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Week 1 to 4 - Snowball warmup')
    .setHelpText('15 sends per subdomain per day in Week 1, 25 in Week 2, 35 in Week 3, 50 in Week 4. Total daily volume scales from 150 to 500 across the pool. Negative-signal detector pauses any subdomain showing inbox issues.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('Month 2 to 3 - Full ramp')
    .setHelpText('500 sends per day, all subdomains live. Weekly written brief: account list, signal logic, sequence variants, reply rate, meetings booked. You review and approve any new sequence copy; three business days of silence counts as approval.'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('What we commit to during the pilot')
    .setHelpText(
      '- Build the engine end to end across ten subdomains\n' +
      '- Hand-pick a targeted account list at the start of every campaign\n' +
      '- Persona-by-persona copy adapted from your existing methodology\n' +
      '- Four-touch sequence per persona, all variants tested\n' +
      '- Subdomain health monitoring with auto-pause on negative signals\n' +
      '- Reply routing to your inbox within 60 seconds of delivery\n' +
      '- Weekly written brief covering accounts, signals, copy, reply rate, meetings\n' +
      '- Sender stickiness so every recipient sees one human consistently\n' +
      '- Maintain GDPR Article 32 technical and organisational measures (TLS 1.2+, AES-256, MFA, daily backups)\n' +
      '- Full operational transparency throughout the term'));

  newItems.push(form.addSectionHeaderItem()
    .setTitle('What you need to keep doing')
    .setHelpText(
      '- Take the booked intro calls when they hit your endpoint\n' +
      '- Respond to our operational queries within two business days during the term\n' +
      '- Tell us if your ICP, intro routing, or buyer titles change\n' +
      '- Review and approve any new sequence copy we send (three business days of silence equals approval)\n' +
      '- Keep your DNS zone intact for the duration of the pilot'));

  // Move new items to the top using INDEX-based moveItem (the
  // (Item, int) signature rejects SectionHeaderItem at runtime).
  // After addSectionHeaderItem appends to the end, new items sit at
  // indices [originalCount, originalCount + newItems.length - 1].
  // Repeatedly moving the LAST item to position 0 walks them to the
  // top while preserving their display order.
  var endIndex = originalCount + newItems.length - 1;
  for (var j = 0; j < newItems.length; j++) {
    form.moveItem(endIndex, 0);
  }

  var editUrl = form.getEditUrl();
  var publishedUrl = form.getPublishedUrl();
  Logger.log('=========================================================');
  Logger.log('Intro section added to Aureon onboarding form.');
  Logger.log('');
  Logger.log('Edit URL: ' + editUrl);
  Logger.log('Live URL: ' + publishedUrl);
  Logger.log('=========================================================');
  return editUrl;
}
