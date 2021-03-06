"""
Created on Apr 12, 2019
@author: Yuedong Chen
"""
import os
import glob
import pickle
from mtcnn import detect_faces
from align_face import AlignFace
from PIL import Image
import cv2
import random
import argparse
import inspect





def make_dir_if_not_exist(path):
    if not os.path.exists(path):
        os.makedirs(path)
    return path


class ProcessCKP(object):
    """docstring for ProcessCKP"""
    def __init__(self):
        super(ProcessCKP, self).__init__()
        self.ALL_EXPRESSIONS = ['Neutral', 'Anger', 'Contempt', 'Disgust', 'Fear', 'Happiness', 'Sadness', 'Surprise']
        self.FILTER_EXPRESSIONS = ['Anger', 'Disgust', 'Fear', 'Happiness', 'Sadness', 'Surprise']
        
    def initialize(self, opt):
        self.raw_img_dir = os.path.join(opt.raw_dir, "cohn-kanade-images")
        assert os.path.isdir(self.raw_img_dir), "Please download CK+ dataset 'cohn-kanade-images.zip' and extract it to %s." % self.raw_img_dir
        self.raw_label_dir = os.path.join(opt.raw_dir, "Emotion")
        assert os.path.isdir(self.raw_label_dir), "Please download CK+ dataset 'Emotion_labels.zip' and extract it to %s." % self.raw_label_dir

        self.n_folds = opt.n_folds
        self.out_root_dir = make_dir_if_not_exist(os.path.join(opt.out_dir))
        self.out_img_dir = make_dir_if_not_exist(os.path.join(self.out_root_dir, "imgs"))
        self.saved_label_path = os.path.join(self.out_root_dir, "emotion_labels.pkl")
        self.saved_bbox_landmark_path = os.path.join(self.out_root_dir, "bbox_landmark_mtcnn.pkl")

        self.is_debug = opt.is_debug
        if self.is_debug:
            with open(os.path.join(self.out_root_dir, "aus_openface_bak.pkl"), 'rb') as f:
                self.aus_dict = pickle.load(f, encoding='latin1')

    def run(self):
        print(">>> Start preprocessing CK+ dataset.")
        print(">>> Getting images labels.")
        self.label_dict = self.get_label_dict()
        print(">>> Getting images path.")
        self.image_list = self.get_image_list()
        print(">>> Filtering images by labels.")
        self.label_dict, self.image_list = self.filter_images()
        self.dump_dict_to_pkl(self.label_dict, self.saved_label_path)
        print(">>> Start detecting faces.")
        self.bbox_landmark_dict = self.detect_all_faces()
        self.dump_dict_to_pkl(self.bbox_landmark_dict, self.saved_bbox_landmark_path)
        print(">>> Start algining faces.")
        self.algin_all_faces()
        print(">>> Start generating train and test files.")
        self.split_dataset()

    def get_label_dict(self):
        label_dict = {}
        for subject in glob.glob(os.path.join(self.raw_label_dir, '*/')):
            for clip in glob.glob(os.path.join(subject, '*/')):
                for item in glob.glob(os.path.join(clip, '*.txt')):
                    with open(item, 'r') as f:
                        content = f.readlines()[0].strip()
                        cur_label = self.ALL_EXPRESSIONS[int(float(content))]
                        cur_key = ('_').join(os.path.basename(item).split('_')[:2])
                        label_dict[cur_key] = cur_label
        return label_dict

    def get_image_list(self):
        image_list = []
        for subject in glob.glob(os.path.join(self.raw_img_dir, '*/')):
            for clip in glob.glob(os.path.join(subject, '*/')):
                items = sorted(glob.glob(os.path.join(clip, '*.png')))
                image_list.extend(items[-3:])
        print(len(image_list))
        return image_list

    def filter_images(self):
        new_label_dict = {}
        new_image_list = []

        for image_path in self.image_list:
            image_basename = os.path.basename(image_path)
            cur_key = ('_').join(image_basename.split('_')[:2])
            if (cur_key in self.label_dict) and (self.label_dict[cur_key] in self.FILTER_EXPRESSIONS):
                new_label_dict[image_basename] = self.label_dict[cur_key]
                new_image_list.append(image_path)

        print(len(new_label_dict.keys()), len(new_image_list))
        return new_label_dict, new_image_list
        
    def dump_dict_to_pkl(self, saved_dict, saved_path):
        with open(saved_path, 'wb') as f:
            pickle.dump(saved_dict, f)
        print("<<< Saved to %s." % saved_path)

    def detect_all_faces(self):
        bbox_landmark_dict = {}
        for img_path in self.image_list:
            print(img_path)
            try:
                cur_img = Image.open(img_path).convert('RGB')
            except:
                continue
            bbox, landmark = detect_faces(cur_img)
            bbox_landmark_dict[img_path] = [bbox, landmark]
        return bbox_landmark_dict

    def algin_all_faces(self):
        align_face = AlignFace(im_resize=(80, 80))

        cnt = 0
        for img_path, value in sorted(self.bbox_landmark_dict.items()):
            if len(value) < 2: 
                continue
            print("%03d" % cnt, img_path)
            cnt += 1 
            bbox, landmark = value
            img = cv2.imread(img_path)
            converted_landmark = []
            try:
                for i in range(5):
                    converted_landmark.append([landmark[0][i], landmark[0][i+5]])
            except IndexError:
                continue
            converted_img = align_face(img, converted_landmark)
            converted_imgname = os.path.basename(img_path)
            cv2.imwrite(os.path.join(self.out_img_dir, converted_imgname), converted_img)

    def split_dataset(self):
        """
        Split dataset into train and test set, subject-independent
        """
        # store images based on their subjects
        label_imgs_dict = {}
        for img_path in sorted(glob.glob(os.path.join(self.out_img_dir, '*.png'))):
            img_name = os.path.basename(img_path)
            if self.is_debug and (not img_name in self.aus_dict):
                print("Cannot find AUs of %s." % img_name)
                continue
            subject_name = img_name.split('_')[0]
            if not subject_name in label_imgs_dict:
                label_imgs_dict[subject_name] = []
            label_imgs_dict[subject_name].append(img_name)

        # split subject into 5 equal folds
        subjects = sorted(list(label_imgs_dict.keys()))
        division = len(subjects) / float(self.n_folds)
        subjects_folds = [subjects[int(round(division * i)): int(round(division * (i + 1)))] for i in range(self.n_folds)]

        # select one fold as test fold
        for idx in range(self.n_folds):
            test_subjects = subjects_folds[idx]
            train_list = []
            test_list = []
            for k, v in label_imgs_dict.items():
                if k in test_subjects:
                    test_list.extend(v)
                else:
                    train_list.extend(v)

            with open(os.path.join(self.out_root_dir, "train_ids_%d.csv" % idx), 'w') as f:
                f.write('\n'.join(sorted(train_list)))
            with open(os.path.join(self.out_root_dir, "test_ids_%d.csv" % idx), 'w') as f:
                f.write('\n'.join(sorted(test_list)))
            print("<<< [Fold %d] Successully split dataset, L(%d). Train: S(%d)L(%d); Test: S(%d)L(%d)" % \
                (idx, len(train_list) + len(test_list), len(subjects)-len(test_subjects), len(train_list), 
                    len(test_subjects), len(test_list)))


def main():
    processCKP = ProcessCKP()
    cur_file_path = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--raw_dir', type=str, default=os.path.join(cur_file_path, '../datasets/CKPlus/RAW'), help='raw image dataset dir.')
    parser.add_argument('--out_dir', type=str, default=os.path.join(cur_file_path, '../datasets/CKPlus'), help='image output dir.')
    parser.add_argument('--n_folds', type=int, default=5, help='number of fold for spliting train and test set.')
    parser.add_argument('--is_debug', action='store_true', help='Use debug mode.')
    opt = parser.parse_args()

    processCKP.initialize(opt)
    processCKP.run()


if __name__ == "__main__":
    main()
