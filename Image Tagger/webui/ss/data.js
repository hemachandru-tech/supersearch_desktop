/* Mock dataset for the Super Search Desktop prototype.
   Mirrors the real schema: player_names, event_type, mood, action, location,
   jersey_color, apparel, crowd_present, caption, tournament + faces[] for review. */
(function () {
  // Photo placeholder: deterministic gradient + subtle grain so the grid reads as a
  // real media library without using copyrighted photos. Swap for real /api/thumb later.
  const GRADS = [
    ['#3a2f12', '#171821'], ['#12233a', '#161821'], ['#2a1230', '#181620'],
    ['#123a2c', '#161a21'], ['#3a1218', '#1a1620'], ['#2f3a12', '#191b20'],
    ['#1a2a3a', '#171821'], ['#3a2a12', '#1b1820'],
  ];

  const ROSTER = [
    'MS Dhoni', 'Ruturaj Gaikwad', 'Ravindra Jadeja', 'Shivam Dube',
    'Devon Conway', 'Matheesha Pathirana', 'Deepak Chahar', 'Moeen Ali',
    'Rachin Ravindra', 'Daryl Mitchell', 'Sameer Rizvi', 'Ajinkya Rahane',
    'Tushar Deshpande', 'Mukesh Choudhary', 'Stephen Fleming',
  ];

  const EVENTS = ['match', 'practice', 'training', 'promotional event', 'press conference', 'fan event', 'travel'];
  const MOODS = ['tense', 'focused', 'relaxed', 'energetic', 'joyful', 'determined', 'celebrating'];
  const ACTIONS = ['walking', 'sitting', 'batting', 'bowling', 'fielding', 'posing', 'celebrating', 'training', 'practicing'];
  const JERSEYS = ['Yellow', 'Blue', 'White', 'Black'];
  const APPAREL = ['Match Jersey', 'Training Kit', 'Casual', 'Formal', 'Auction Suit'];
  // Pre-load fallbacks; overwritten at runtime by /api/filters (see index.html loadData).
  const LOCATIONS = ['stadium', 'field', 'pitch', 'practice nets', 'dressing room', 'hotel', 'airport', 'gym', 'grandstand', 'pavilion'];
  const JERSEY_TYPES = ['Match Jersey', 'Practice Jersey', 'Off Field kit', 'Casual Attire', 'Unknown'];

  let _id = 0;
  function img(o) {
    _id++;
    const g = GRADS[_id % GRADS.length];
    return Object.assign({
      id: 'img-' + _id,
      grad: g, seed: _id,
      embedded: true, starred: false,
      location: 'field', crowd: 'Yes', jersey: 'Yellow',
      apparel: 'Match Jersey', tournament: 'IPL 2026',
      dims: '4096 × 2731', size: '6.2 MB',
      faces: [],
    }, o);
  }

  const IMAGES = [
    img({ file: 'csk-team-walk-off-guwahati-v0.webp', format: 'webp', players: ['MS Dhoni', 'Ruturaj Gaikwad'], event: 'match', mood: 'tense', action: 'walking', caption: 'Chennai Super Kings players, including MS Dhoni and Devon Conway, walk off after a tight finish in Guwahati.', crowd: 'Yes',
      faces: [{ name: 'MS Dhoni', conf: 0.93, status: 'confirmed' }, { name: 'Ruturaj Gaikwad', conf: 0.88, status: 'confirmed' }, { name: 'Devon Conway', conf: 0.61, status: 'review' }] }),
    img({ file: 'csk-ipl-2026-auction-squad.jpg', format: 'jpg', players: ['Ruturaj Gaikwad', 'MS Dhoni'], event: 'promotional event', mood: 'focused', action: 'sitting', caption: 'Captain Ruturaj Gaikwad and MS Dhoni at the IPL 2026 auction table.', location: 'auction hall', crowd: 'No', apparel: 'Auction Suit',
      faces: [{ name: 'Ruturaj Gaikwad', conf: 0.95, status: 'confirmed' }, { name: 'MS Dhoni', conf: 0.91, status: 'confirmed' }] }),
    img({ file: 'CSK-RR-6.jpg', format: 'jpg', players: [], event: 'practice', mood: 'relaxed', action: 'practicing', caption: 'Net session ahead of the Chennai vs Rajasthan fixture.', location: 'nets',
      faces: [{ name: 'Unknown', conf: 0.34, status: 'rejected' }] }),
    img({ file: 'CSKNEWS_IMG20240323.jpg', format: 'jpg', players: ['Ruturaj Gaikwad', 'MS Dhoni'], event: 'match', mood: 'determined', action: 'walking', caption: 'CSK take the field for the season opener under the lights.',
      faces: [{ name: 'Ruturaj Gaikwad', conf: 0.9, status: 'confirmed' }, { name: 'MS Dhoni', conf: 0.86, status: 'confirmed' }] }),
    img({ file: 'chennai-super-kings-celebrate.webp', format: 'webp', players: ['Ravindra Jadeja'], event: 'match', mood: 'energetic', action: 'celebrating', caption: 'Ravindra Jadeja celebrates a key wicket with the team.',
      faces: [{ name: 'Ravindra Jadeja', conf: 0.92, status: 'confirmed' }, { name: 'Shivam Dube', conf: 0.55, status: 'review' }] }),
    img({ file: '16csk-squad1-1.webp', format: 'webp', players: ['MS Dhoni', 'Ruturaj Gaikwad', 'Shivam Dube'], event: 'promotional event', mood: 'joyful', action: 'posing', caption: 'Squad photo for the IPL 2026 jersey launch.', crowd: 'No',
      faces: [{ name: 'MS Dhoni', conf: 0.94, status: 'confirmed' }, { name: 'Ruturaj Gaikwad', conf: 0.89, status: 'confirmed' }, { name: 'Shivam Dube', conf: 0.83, status: 'confirmed' }] }),
    img({ file: 'csk-training-chepauk-01.jpg', format: 'jpg', players: ['Matheesha Pathirana'], event: 'training', mood: 'focused', action: 'bowling', caption: 'Matheesha Pathirana works on his slingy yorkers at Chepauk.', location: 'nets', jersey: 'Blue', apparel: 'Training Kit', crowd: 'No',
      faces: [{ name: 'Matheesha Pathirana', conf: 0.87, status: 'confirmed' }] }),
    img({ file: 'dhoni-keeping-stumps.jpg', format: 'jpg', players: ['MS Dhoni'], event: 'match', mood: 'focused', action: 'fielding', caption: 'MS Dhoni behind the stumps, eyeing a stumping chance.',
      faces: [{ name: 'MS Dhoni', conf: 0.96, status: 'confirmed' }] }),
    img({ file: 'gaikwad-cover-drive.jpg', format: 'jpg', players: ['Ruturaj Gaikwad'], event: 'match', mood: 'determined', action: 'batting', caption: 'Ruturaj Gaikwad leans into a trademark cover drive.',
      faces: [{ name: 'Ruturaj Gaikwad', conf: 0.93, status: 'confirmed' }] }),
    img({ file: 'csk-huddle-pregame.webp', format: 'webp', players: ['MS Dhoni', 'Ravindra Jadeja', 'Ruturaj Gaikwad'], event: 'match', mood: 'tense', action: 'standing', caption: 'Pre-game huddle before the Qualifier.',
      faces: [{ name: 'MS Dhoni', conf: 0.9, status: 'confirmed' }, { name: 'Ravindra Jadeja', conf: 0.82, status: 'confirmed' }] }),
    img({ file: 'conway-mitchell-partnership.jpg', format: 'jpg', players: ['Devon Conway', 'Daryl Mitchell'], event: 'match', mood: 'focused', action: 'batting', caption: 'Conway and Mitchell build a steady partnership.',
      faces: [{ name: 'Devon Conway', conf: 0.85, status: 'confirmed' }, { name: 'Daryl Mitchell', conf: 0.58, status: 'review' }] }),
    img({ file: 'jadeja-fielding-dive.jpg', format: 'jpg', players: ['Ravindra Jadeja'], event: 'match', mood: 'energetic', action: 'fielding', caption: 'Jadeja dives full-length to save a boundary.',
      faces: [{ name: 'Ravindra Jadeja', conf: 0.94, status: 'confirmed' }] }),
    img({ file: 'csk-press-conf-fleming.jpg', format: 'jpg', players: ['Stephen Fleming'], event: 'press conference', mood: 'relaxed', action: 'sitting', caption: 'Head coach Stephen Fleming addresses the media.', location: 'press room', jersey: 'Yellow', apparel: 'Casual', crowd: 'No',
      faces: [{ name: 'Stephen Fleming', conf: 0.88, status: 'confirmed' }] }),
    img({ file: 'fan-event-chennai-2026.webp', format: 'webp', players: ['Shivam Dube', 'Sameer Rizvi'], event: 'fan event', mood: 'joyful', action: 'posing', caption: 'Players greet members at the CSK fan day.', location: 'stadium concourse',
      faces: [{ name: 'Shivam Dube', conf: 0.8, status: 'confirmed' }, { name: 'Sameer Rizvi', conf: 0.49, status: 'review' }] }),
    img({ file: 'team-bus-arrival.jpg', format: 'jpg', players: ['MS Dhoni'], event: 'travel', mood: 'relaxed', action: 'walking', caption: 'The squad arrives at the venue ahead of the night game.', location: 'stadium entrance', jersey: 'Black', apparel: 'Casual',
      faces: [{ name: 'MS Dhoni', conf: 0.91, status: 'confirmed' }] }),
    img({ file: 'chahar-celebration-wicket.jpg', format: 'jpg', players: ['Deepak Chahar'], event: 'match', mood: 'celebrating', action: 'celebrating', caption: 'Deepak Chahar roars after an early breakthrough.',
      faces: [{ name: 'Deepak Chahar', conf: 0.86, status: 'confirmed' }] }),
    img({ file: 'IMG_8841.CR3', format: 'raw', players: [], event: 'match', mood: '', action: '', caption: 'RAW capture — convert to JPEG before tagging.', error: true, embedded: false,
      faces: [] }),
    img({ file: 'moeen-rachin-nets.webp', format: 'webp', players: ['Moeen Ali', 'Rachin Ravindra'], event: 'training', mood: 'focused', action: 'practicing', caption: 'Moeen Ali and Rachin Ravindra at the spin-bowling nets.', location: 'nets', jersey: 'Blue', apparel: 'Training Kit', crowd: 'No',
      faces: [{ name: 'Moeen Ali', conf: 0.84, status: 'confirmed' }, { name: 'Rachin Ravindra', conf: 0.79, status: 'confirmed' }] }),
  ];

  // Anything with a face flagged "review" or "rejected" surfaces in Face Review.
  const REVIEW_COUNT = IMAGES.filter(i => i.faces.some(f => f.status === 'review')).length;

  window.SS_DATA = {
    IMAGES, ROSTER, EVENTS, MOODS, ACTIONS, JERSEYS, APPAREL, LOCATIONS, JERSEY_TYPES, REVIEW_COUNT,
    // LIBRARY filter options (distinct values in tagged content); filled by /api/filters at runtime.
    LIB: { players: [], events: [], moods: [], actions: [], jerseyTypes: [], locations: [] },
    STATUS: { geminiKeys: 1, metadata: 'piexif', tagged: IMAGES.filter(i => i.embedded).length, total: IMAGES.length, exiftool: false },
  };
})();
